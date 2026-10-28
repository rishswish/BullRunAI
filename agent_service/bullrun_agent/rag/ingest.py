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
from pathlib import Path

from ..config import get_settings
from ..llm import get_embeddings
from .chunking import chunk_filing
from .edgar import fetch_text, list_filings
from .store import HybridIndex

DEFAULT_TICKERS = ["NVDA", "AAPL", "MSFT", "TSLA", "AMZN", "GOOGL", "META", "AMD"]


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tickers", nargs="+", default=DEFAULT_TICKERS)
    ap.add_argument("--per-ticker", type=int, default=2, help="filings per ticker (latest 10-K + 10-Q)")
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
    index = HybridIndex.build(chunks, get_embeddings(s))
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
