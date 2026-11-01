"""Filings RAG: EDGAR ingest -> section-aware chunks -> hybrid BM25 + dense index.

The index lives in Cloud Storage. Each process loads it once, then checks every few
minutes whether the scheduled ingest job published a newer one and swaps it in. A
question about a company that isn't indexed yet fetches its filings on the spot,
adds them, and publishes the bigger index for every other instance.
"""
from __future__ import annotations

import logging
import tempfile
import threading
import time
from pathlib import Path

from ..config import get_settings
from ..llm import get_embeddings
from .store import Hit, HybridIndex

log = logging.getLogger(__name__)
_index: HybridIndex | None = None
_generation: int | None = None  # Cloud Storage version of the index we hold
_lock = threading.Lock()
_add_lock = threading.Lock()
_last_attempt = 0.0
_last_check = 0.0
RETRY_SECONDS = 300  # if the index isn't available yet (e.g. ingest still running), retry later
FILES = ("vectors.npy", "chunks.jsonl")  # chunks.jsonl is written last and marks the version


def _bucket_prefix(uri: str):
    from google.cloud import storage

    bucket_name, _, prefix = uri.removeprefix("gs://").partition("/")
    return storage.Client().bucket(bucket_name), prefix.rstrip("/")


def _remote_generation(uri: str) -> int | None:
    bucket, prefix = _bucket_prefix(uri)
    blob = bucket.get_blob(f"{prefix}/chunks.jsonl")
    return blob.generation if blob else None


def _download(uri: str, dest: Path) -> int | None:
    bucket, prefix = _bucket_prefix(uri)
    dest.mkdir(parents=True, exist_ok=True)
    gen = None
    for name in FILES:
        blob = bucket.blob(f"{prefix}/{name}")
        blob.download_to_filename(dest / name)
        gen = blob.generation
    return gen


def get_index() -> HybridIndex | None:
    """The current index: loaded once per process, refreshed when a newer one is published."""
    global _index, _generation, _last_attempt, _last_check
    if _index is not None:
        _maybe_reload()
        return _index
    with _lock:
        if _index is None and time.time() - _last_attempt > RETRY_SECONDS:
            _last_attempt = time.time()
            s = get_settings()
            path = Path(s.index_dir)
            try:
                if not (path / "chunks.jsonl").exists() and s.index_gcs_uri:
                    log.info("downloading filings index from %s", s.index_gcs_uri)
                    _generation = _download(s.index_gcs_uri, path)
                if (path / "chunks.jsonl").exists():
                    _index = HybridIndex.load(path)
                    _last_check = time.time()
                    log.info("loaded filings index: %d chunks, tickers=%s", len(_index.chunks), _index.tickers)
            except Exception as e:  # missing/partial index must never take the API down
                log.warning("filings index unavailable (%s); will retry in %ds", e, RETRY_SECONDS)
    return _index


def _maybe_reload(force: bool = False) -> None:
    """Swap in a newer published index (cheap metadata check, at most every few minutes)."""
    global _index, _generation, _last_check
    s = get_settings()
    if not s.index_gcs_uri or (not force and time.time() - _last_check < s.index_reload_seconds):
        return
    with _lock:
        _last_check = time.time()
        try:
            gen = _remote_generation(s.index_gcs_uri)
            if gen is None or gen == _generation:
                return
            tmp = Path(tempfile.mkdtemp(prefix="filings_"))
            got = _download(s.index_gcs_uri, tmp)
            _index, _generation = HybridIndex.load(tmp), got
            log.info("reloaded filings index (version %s): %d chunks, tickers=%s", got, len(_index.chunks),
                     _index.tickers)
        except Exception as e:  # a half-written upload or a blip: keep serving the old one
            log.warning("filings index reload skipped: %s", e)


def publish(index: HybridIndex) -> bool:
    """Save locally and, on Cloud Run, upload. False if someone else published first."""
    global _generation
    s = get_settings()
    index.save(Path(s.index_dir))
    if not s.index_gcs_uri:
        return True
    from google.api_core.exceptions import PreconditionFailed

    bucket, prefix = _bucket_prefix(s.index_gcs_uri)
    try:
        bucket.blob(f"{prefix}/vectors.npy").upload_from_filename(Path(s.index_dir) / "vectors.npy")
        blob = bucket.blob(f"{prefix}/chunks.jsonl")
        # only replace the version we started from, so two writers can't silently undo each other
        blob.upload_from_filename(Path(s.index_dir) / "chunks.jsonl", if_generation_match=_generation or 0)
    except PreconditionFailed:
        return False
    _generation = blob.generation
    return True


def _embedder():
    from .ingest import ThrottledEmbeddings

    return ThrottledEmbeddings(get_embeddings(), per_minute=get_settings().embed_per_minute)


def add_company(ticker: str) -> dict:
    """Fetch and index a company's latest 10-K and 10-Q (the first time anyone asks about it)."""
    global _index
    from .edgar import ticker_map
    from .updater import refresh

    t = ticker.upper()
    with _add_lock:
        idx = get_index()
        if idx is not None and t in idx.tickers:
            return {"status": "already indexed"}
        if t not in ticker_map():
            return {"status": "not an SEC filer",
                    "note": f"{t} has no SEC 10-K/10-Q (it may be an ETF, a fund or a non-US listing)."}
        for _ in range(3):
            new, changes = refresh(idx, [t], _embedder())
            if not changes:
                return {"status": "no filings", "note": f"No recent 10-K or 10-Q on EDGAR for {t}."}
            if publish(new):
                with _lock:
                    _index = new
                log.info("indexed %s on demand: %s", t, changes)
                return {"status": "indexed", "changes": changes}
            _maybe_reload(force=True)  # another instance published meanwhile: build on top of theirs
            idx = get_index()
            if idx is not None and t in idx.tickers:
                return {"status": "already indexed"}
        return {"status": "busy", "note": "The filings index is being updated; try again in a minute."}


def set_index(index: HybridIndex | None) -> None:
    """Inject an index (tests)."""
    global _index, _last_attempt, _generation
    _index, _generation = index, None
    _last_attempt = 0.0


def search_filings(query: str, ticker: str | None = None, form: str | None = None,
                   k: int | None = None) -> dict:
    s = get_settings()
    idx = get_index()
    t = ticker.upper().strip() if ticker else None
    added = None
    if t and s.on_demand_filings and (idx is None or t not in idx.tickers):
        try:
            added = add_company(t)
        except Exception as e:  # EDGAR down, embedding quota...: answer what we can
            log.warning("on-demand indexing of %s failed: %s", t, e)
            added = {"status": "failed", "note": f"Couldn't fetch {t}'s filings right now."}
        idx = get_index()
    if idx is None:
        return {"results": [], "error": "Filings index not built yet. Run: python -m bullrun_agent.rag.ingest"}
    hits: list[Hit] = idx.search(query, get_embeddings(), k=k or s.retrieval_k, ticker=t, form=form)
    if not hits and t:
        note = (added or {}).get("note") or f"No indexed filings for {t}."
        return {"results": [], "note": note, "indexed_tickers": idx.tickers}
    out = {
        "results": [{"source_id": f"S{i + 1}", "text": h.text[:1500], "citation": h.citation(),
                     "score": h.score} for i, h in enumerate(hits)],
        "indexed_tickers": idx.tickers,
    }
    if added and added.get("status") == "indexed":
        out["note"] = f"Fetched {t}'s latest filings from SEC EDGAR just now."
    return out
