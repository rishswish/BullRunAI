"""Build the filings index.

    python -m bullrun_agent.rag.ingest --tickers NVDA AAPL MSFT TSLA AMZN --per-ticker 2
    python -m bullrun_agent.rag.ingest --upload gs://my-bucket/filings_index

Fetches the latest 10-K/10-Q per ticker from EDGAR, chunks by section, embeds,
and writes vectors.npy + chunks.jsonl to INDEX_DIR (optionally uploads to GCS).
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import time
from pathlib import Path

from ..config import get_settings
from ..llm import get_embeddings
from .chunking import chunk_filing
from .edgar import fetch_text, list_filings
from .store import HybridIndex

DEFAULT_TICKERS = ["NVDA", "AAPL", "MSFT", "TSLA", "AMZN", "GOOGL", "META", "AMD"]


class ThrottledEmbeddings:
    """Keeps under a per-minute quota (Gemini free tier: 100 texts/min) and retries 429s."""

    def __init__(self, base, per_minute: int = 90, batch: int = 30, retries: int = 6):
        self.base, self.per_minute, self.batch, self.retries = base, per_minute, batch, retries
        self._sent: list[float] = []

    def _wait_for(self, n: int) -> None:
        while True:
            now = time.time()
            self._sent = [t for t in self._sent if now - t < 60]
            if len(self._sent) + n <= self.per_minute:
                return
            time.sleep(60 - (now - self._sent[0]) + 0.5)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), self.batch):
            part = texts[i:i + self.batch]
            for attempt in range(self.retries):
                self._wait_for(len(part))
                try:
                    vecs = self.base.embed_documents(part)
                    self._sent += [time.time()] * len(part)
                    out.extend(vecs)
                    break
                except Exception as e:  # noqa: BLE001
                    msg = str(e)
                    if "429" not in msg and "RESOURCE_EXHAUSTED" not in msg or attempt == self.retries - 1:
                        raise
                    m = re.search(r"retry in ([\d.]+)s", msg)
                    delay = float(m.group(1)) + 2 if m else 30
                    logging.warning("rate limited, waiting %.0fs", delay)
                    time.sleep(delay)
            logging.info("embedded %d/%d chunks", min(i + self.batch, len(texts)), len(texts))
        return out

    def embed_query(self, text: str) -> list[float]:
        return self.base.embed_query(text)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tickers", nargs="+", default=DEFAULT_TICKERS)
    ap.add_argument("--per-ticker", type=int, default=1, help="filings per ticker (most recent first)")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--upload", default=None, help="gs://bucket/prefix to upload the index to")
    args = ap.parse_args()

    s = get_settings()
    out = args.out or Path(s.index_dir)
    chunks = []
    manifest = []
    for t in args.tickers:
        try:
            filings = list_filings(t, limit=args.per_ticker)
        except KeyError:
            logging.warning("unknown ticker %s, skipping", t)
            continue
        for f in filings:
            f = fetch_text(f)
            meta = {"ticker": f.ticker, "company": f.company, "form": f.form, "filed": f.filed,
                    "period": f.period, "url": f.url}
            cs = chunk_filing(f.text, meta)
            chunks.extend(cs)
            manifest.append({**meta, "chunks": len(cs)})
            logging.info("%s %s %s -> %d chunks", f.ticker, f.form, f.filed, len(cs))

    logging.info("embedding %d chunks with %s/%s", len(chunks), s.embedding_provider, s.embedding_model)
    index = HybridIndex.build(chunks, ThrottledEmbeddings(get_embeddings(s)), batch=len(chunks) or 1)
    index.save(out)
    (out / "manifest.json").write_text(json.dumps({"embedding_provider": s.embedding_provider,
                                                   "embedding_model": s.embedding_model,
                                                   "filings": manifest}, indent=2))
    logging.info("saved index to %s", out)

    if args.upload:
        from google.cloud import storage

        bucket_name, _, prefix = args.upload.removeprefix("gs://").partition("/")
        bucket = storage.Client().bucket(bucket_name)
        for name in ("vectors.npy", "chunks.jsonl", "manifest.json"):
            bucket.blob(f"{prefix.rstrip('/')}/{name}").upload_from_filename(out / name)
        logging.info("uploaded index to %s", args.upload)


if __name__ == "__main__":
    main()
