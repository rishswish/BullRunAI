"""Keep the filings index up to date (run daily by Cloud Scheduler).

    python -m bullrun_agent.rag.ingest                       # refresh the default companies
    python -m bullrun_agent.rag.ingest --with-users          # + every user's watchlist and holdings
    python -m bullrun_agent.rag.ingest --upload gs://my-bucket/filings_index
    python -m bullrun_agent.rag.ingest --rebuild             # start from scratch

For each company it keeps the latest 10-K, the latest 10-Q and 8-Ks from the last 120
days (at most 6). Only filings that are new since the last run are downloaded and
embedded; superseded 10-K/10-Qs and older 8-Ks are dropped.
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


def user_tickers(limit: int = 60) -> list[str]:
    """Tickers on users' watchlists and in their holdings, most common first."""
    from collections import Counter

    from ..data_sources import get_user_store

    store = get_user_store()
    if not hasattr(store, "db"):
        return []
    counts: Counter = Counter()
    for doc in store.db.collection("users").stream():
        d = doc.to_dict() or {}
        counts.update((d.get("onboarding") or {}).get("watchlist") or [])
        counts.update(h.get("symbol") for h in d.get("manual_holdings") or [] if h.get("symbol"))
    return [t.upper() for t, _ in counts.most_common(limit) if t and re.fullmatch(r"[A-Za-z.]{1,6}", t)]


def main() -> None:
    from . import get_index, publish, set_index
    from .updater import refresh

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tickers", nargs="+", default=DEFAULT_TICKERS)
    ap.add_argument("--with-users", action="store_true", help="also cover users' watchlists and holdings")
    ap.add_argument("--rebuild", action="store_true", help="ignore the existing index")
    ap.add_argument("--upload", default=None, help="gs://bucket/prefix (defaults to INDEX_GCS_URI)")
    args = ap.parse_args()

    s = get_settings()
    if args.upload:
        s.index_gcs_uri = args.upload
    existing = None if args.rebuild else get_index()
    tickers = set(args.tickers) | set(existing.tickers if existing else [])
    if args.with_users:
        try:
            tickers |= set(user_tickers())
        except Exception as e:  # Firestore down shouldn't stop the default refresh
            logging.warning("could not read user tickers: %s", e)
    logging.info("refreshing %d companies: %s", len(tickers), ", ".join(sorted(tickers)))

    index, changes = refresh(existing, sorted(tickers),
                             ThrottledEmbeddings(get_embeddings(s), per_minute=s.embed_per_minute))
    if not changes:
        logging.info("no new filings; index unchanged (%d chunks)", len(index.chunks))
        return
    for c in changes:
        logging.info(c)
    if not publish(index):
        raise SystemExit("index changed while refreshing (an on-demand add?); the next run will pick it up")
    set_index(index)
    (Path(s.index_dir) / "manifest.json").write_text(json.dumps(
        {"embedding_model": s.embedding_model, "tickers": index.tickers, "changes": changes}, indent=2))
    logging.info("published index: %d chunks, %d companies", len(index.chunks), len(index.tickers))


if __name__ == "__main__":
    main()
