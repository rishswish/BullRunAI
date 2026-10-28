"""Filings RAG: EDGAR ingest -> section-aware chunks -> hybrid BM25 + dense index."""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from ..config import get_settings
from ..llm import get_embeddings
from .store import Hit, HybridIndex

log = logging.getLogger(__name__)
_index: HybridIndex | None = None
_lock = threading.Lock()
_last_attempt = 0.0
RETRY_SECONDS = 300  # if the index isn't available yet (e.g. ingest still running), retry later


def _download_from_gcs(uri: str, dest: Path) -> None:
    from google.cloud import storage

    bucket_name, _, prefix = uri.removeprefix("gs://").partition("/")
    bucket = storage.Client().bucket(bucket_name)
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("vectors.npy", "chunks.jsonl"):
        bucket.blob(f"{prefix.rstrip('/')}/{name}").download_to_filename(dest / name)


def get_index() -> HybridIndex | None:
    """Lazy-load the index once per process (from disk, or GCS on Cloud Run)."""
    global _index, _last_attempt
    if _index is not None:
        return _index
    with _lock:
        if _index is None and time.time() - _last_attempt > RETRY_SECONDS:
            _last_attempt = time.time()
            s = get_settings()
            path = Path(s.index_dir)
            try:
                if not (path / "chunks.jsonl").exists() and s.index_gcs_uri:
                    log.info("downloading filings index from %s", s.index_gcs_uri)
                    _download_from_gcs(s.index_gcs_uri, path)
                if (path / "chunks.jsonl").exists():
                    _index = HybridIndex.load(path)
                    log.info("loaded filings index: %d chunks, tickers=%s", len(_index.chunks), _index.tickers)
            except Exception as e:  # missing/partial index must never take the API down
                log.warning("filings index unavailable (%s); will retry in %ds", e, RETRY_SECONDS)
    return _index


def set_index(index: HybridIndex | None) -> None:
    """Inject an index (tests)."""
    global _index, _last_attempt
    _index = index
    _last_attempt = 0.0


def search_filings(query: str, ticker: str | None = None, form: str | None = None,
                   k: int | None = None) -> dict:
    idx = get_index()
    if idx is None:
        return {"results": [], "error": "Filings index not built yet. Run: python -m bullrun_agent.rag.ingest"}
    hits: list[Hit] = idx.search(query, get_embeddings(), k=k or get_settings().retrieval_k,
                                 ticker=ticker, form=form)
    if not hits and ticker:
        return {"results": [], "note": f"No indexed filings for {ticker.upper()}. Indexed: {', '.join(idx.tickers)}"}
    return {
        "results": [{"source_id": f"S{i + 1}", "text": h.text[:1500], "citation": h.citation(),
                     "score": h.score} for i, h in enumerate(hits)],
        "indexed_tickers": idx.tickers,
    }
