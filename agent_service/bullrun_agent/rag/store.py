"""Hybrid (BM25 + dense) retrieval index with Reciprocal Rank Fusion.

Why hybrid: filings are full of exact tokens (tickers, "Item 1A", product names,
dollar figures) that BM25 nails and embeddings blur, while paraphrased questions
("what keeps management up at night?") need semantic search. RRF merges the two
rankings without having to calibrate their very different score scales.

Storage is deliberately simple - `vectors.npy` + `chunks.jsonl` in a folder -
which is plenty for a few hundred filings, ships inside the Docker image or a
GCS bucket, and keeps the retrieval maths visible. Swapping in pgvector/Qdrant
only means re-implementing `_dense_search`.
"""
from __future__ import annotations

import json
import logging
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .chunking import Chunk

log = logging.getLogger(__name__)
_TOKEN = re.compile(r"[a-z0-9]+(?:[.'][a-z0-9]+)*")
RRF_K = 60
_STOPWORDS = frozenset("a an and are as at be by for from has have in is it its of on or our that the this to we "
                       "was were what which with does do how".split())


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOPWORDS]


class BM25:
    """Okapi BM25 with Lucene's always-positive IDF, log(1 + (N - df + .5) / (df + .5)).

    rank_bm25's classic IDF goes to zero/negative for terms in half the corpus,
    which breaks small, ticker-filtered candidate sets.
    """

    def __init__(self, docs: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.tfs = [Counter(d) for d in docs]
        self.lens = np.array([len(d) for d in docs], dtype=np.float32)
        self.avgdl = float(self.lens.mean()) if len(docs) else 0.0
        df = Counter(t for d in docs for t in set(d))
        n = len(docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def get_scores(self, query: list[str]) -> np.ndarray:
        scores = np.zeros(len(self.tfs), dtype=np.float32)
        norm = self.k1 * (1 - self.b + self.b * self.lens / (self.avgdl or 1))
        for term in set(query):
            idf = self.idf.get(term)
            if idf is None:
                continue
            tf = np.array([d.get(term, 0) for d in self.tfs], dtype=np.float32)
            scores += idf * tf * (self.k1 + 1) / (tf + norm)
        return scores


@dataclass
class Hit:
    id: str
    text: str
    meta: dict
    score: float
    dense_rank: int | None = None
    bm25_rank: int | None = None

    def citation(self) -> dict:
        m = self.meta
        return {"ticker": m.get("ticker"), "form": m.get("form"), "filed": m.get("filed"),
                "section": m.get("section"), "url": m.get("url"), "chunk_id": self.id}


class HybridIndex:
    def __init__(self, chunks: list[Chunk], vectors: np.ndarray):
        assert len(chunks) == len(vectors), "chunks/vectors length mismatch"
        self.chunks = chunks
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        self.vectors = (vectors / np.where(norms == 0, 1, norms)).astype(np.float32)
        self.bm25 = BM25([tokenize(c.text) for c in chunks])

    # -- persistence ---------------------------------------------------------
    @classmethod
    def build(cls, chunks: list[Chunk], embeddings, batch: int = 64) -> HybridIndex:
        vecs: list[list[float]] = []
        for i in range(0, len(chunks), batch):
            vecs.extend(embeddings.embed_documents([c.text for c in chunks[i:i + batch]]))
            log.info("embedded %d/%d chunks", min(i + batch, len(chunks)), len(chunks))
        return cls(chunks, np.array(vecs, dtype=np.float32))

    def save(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        np.save(path / "vectors.npy", self.vectors)
        with open(path / "chunks.jsonl", "w", encoding="utf-8") as f:
            for c in self.chunks:
                f.write(json.dumps({"id": c.id, "text": c.text, "meta": c.meta}) + "\n")

    @classmethod
    def load(cls, path: Path) -> HybridIndex:
        chunks = [Chunk(**json.loads(line)) for line in open(path / "chunks.jsonl", encoding="utf-8")]
        return cls(chunks, np.load(path / "vectors.npy"))

    @property
    def tickers(self) -> list[str]:
        return sorted({c.meta.get("ticker") for c in self.chunks if c.meta.get("ticker")})

    # -- retrieval ---------------------------------------------------------------
    def _mask(self, ticker: str | None, form: str | None) -> np.ndarray:
        mask = np.ones(len(self.chunks), dtype=bool)
        if ticker:
            mask &= np.array([c.meta.get("ticker") == ticker.upper() for c in self.chunks])
        if form:
            mask &= np.array([c.meta.get("form") == form.upper() for c in self.chunks])
        return mask

    def _dense_search(self, qvec: np.ndarray, mask: np.ndarray, n: int) -> list[int]:
        q = qvec / (np.linalg.norm(qvec) or 1)
        sims = self.vectors @ q
        sims[~mask] = -np.inf
        idx = np.argsort(-sims)[:n]
        return [int(i) for i in idx if np.isfinite(sims[i])]

    def _bm25_search(self, query: str, mask: np.ndarray, n: int) -> list[int]:
        scores = self.bm25.get_scores(tokenize(query))
        scores[~mask] = -np.inf
        idx = np.argsort(-scores)[:n]
        return [int(i) for i in idx if np.isfinite(scores[i]) and scores[i] > 0]

    def search(self, query: str, embeddings, k: int = 6, ticker: str | None = None,
               form: str | None = None, candidates: int = 30) -> list[Hit]:
        if not self.chunks:
            return []
        mask = self._mask(ticker, form)
        if not mask.any():
            return []
        dense = self._dense_search(np.array(embeddings.embed_query(query), dtype=np.float32), mask, candidates)
        sparse = self._bm25_search(query, mask, candidates)
        fused: dict[int, float] = {}
        for rank, i in enumerate(dense):
            fused[i] = fused.get(i, 0) + 1 / (RRF_K + rank + 1)
        for rank, i in enumerate(sparse):
            fused[i] = fused.get(i, 0) + 1 / (RRF_K + rank + 1)
        top = sorted(fused, key=fused.get, reverse=True)[:k]
        d_rank = {i: r for r, i in enumerate(dense)}
        s_rank = {i: r for r, i in enumerate(sparse)}
        return [Hit(id=self.chunks[i].id, text=self.chunks[i].text, meta=self.chunks[i].meta,
                    score=round(fused[i], 5), dense_rank=d_rank.get(i), bm25_rank=s_rank.get(i))
                for i in top]
