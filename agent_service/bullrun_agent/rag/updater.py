"""Keep the filings index current without rebuilding it.

For each company we want its latest 10-K (the annual report), latest 10-Q (the
most recent quarter) and its recent 8-Ks (event reports: earnings releases, deals,
executive changes) from the last few months. A filing is identified by its EDGAR URL, so a refresh only
downloads and embeds filings that aren't in the index yet, keeps the vectors it
already has, and drops filings that have been superseded. Used by the scheduled
ingest job and by search_filings for a company nobody has asked about before.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

import numpy as np

from .chunking import Chunk, chunk_filing, useful_8k
from .edgar import Filing, fetch_text, list_filings
from .store import HybridIndex

log = logging.getLogger(__name__)
FORMS = ("10-K", "10-Q")
EIGHT_K_DAYS = 120  # an 8-K is news: keep about one quarter's worth
EIGHT_K_MAX = 6     # per company, newest first


def latest_filings(ticker: str, today: date | None = None) -> list[Filing]:
    """Newest 10-K, newest 10-Q and recent 8-Ks for a ticker (any may be missing)."""
    cutoff = ((today or date.today()) - timedelta(days=EIGHT_K_DAYS)).isoformat()
    found: dict[str, Filing] = {}
    eight_ks: list[Filing] = []
    for f in list_filings(ticker, forms=(*FORMS, "8-K"), limit=120):  # newest first
        if f.form == "8-K":
            if f.filed >= cutoff and len(eight_ks) < EIGHT_K_MAX and useful_8k(f.items):
                eight_ks.append(f)
        else:
            found.setdefault(f.form, f)
        if len(found) == len(FORMS) and (len(eight_ks) == EIGHT_K_MAX or f.filed < cutoff):
            break
    return [*found.values(), *eight_ks]


def _chunk(f: Filing) -> list[Chunk]:
    f = fetch_text(f)
    meta = {"ticker": f.ticker, "company": f.company, "form": f.form, "filed": f.filed,
            "period": f.period, "url": f.url}
    if f.form == "8-K":
        meta |= {"items": f.items, "accession": f.accession}
    chunks = chunk_filing(f.text, meta)
    log.info("%s %s filed %s -> %d chunks", f.ticker, f.form, f.filed, len(chunks))
    return chunks


def empty_index() -> HybridIndex:
    return HybridIndex([], np.zeros((0, 1), dtype=np.float32))


def refresh(index: HybridIndex | None, tickers: list[str], embeddings) -> tuple[HybridIndex, list[str]]:
    """Bring `tickers` up to date: new filings in, superseded 10-K/10-Qs and 8-Ks older than
    EIGHT_K_DAYS out. Other companies in the index are left untouched.

    Returns the new index and a list of human-readable changes (empty = nothing new).
    """
    index = index or empty_index()
    tickers = sorted({t.upper() for t in tickers})
    wanted: dict[str, list[Filing]] = {}
    for t in tickers:
        try:
            wanted[t] = latest_filings(t)
        except KeyError:
            log.warning("%s is not an SEC filer (ETF or unknown ticker), skipping", t)
        except Exception as e:  # one company's EDGAR hiccup shouldn't stop the rest
            log.warning("could not list filings for %s: %s", t, e)

    have_urls = {c.meta.get("url") for c in index.chunks}
    new_chunks: list[Chunk] = []
    changes: list[str] = []
    failed: set[tuple[str, str]] = set()  # (ticker, form) whose new filing couldn't be fetched
    for fs in wanted.values():
        for f in fs:
            if f.url in have_urls:
                continue
            try:
                new_chunks += _chunk(f)
                changes.append(f"added {f.ticker} {f.form} filed {f.filed}")
            except Exception as e:
                failed.add((f.ticker, f.form))
                log.warning("could not fetch %s %s: %s", f.ticker, f.form, e)

    # Drop a superseded filing only once its replacement is in.
    keep_urls = {f.url for fs in wanted.values() for f in fs}
    kept = [i for i, c in enumerate(index.chunks)
            if c.meta.get("ticker") not in wanted or c.meta.get("url") in keep_urls
            or (c.meta.get("ticker"), c.meta.get("form")) in failed]
    kept_set = set(kept)
    superseded = {c.meta.get("url"): c.meta for i, c in enumerate(index.chunks) if i not in kept_set}
    changes += [f"dropped {m.get('ticker')} {m.get('form')} filed {m.get('filed')}" for m in superseded.values()]

    if not new_chunks and len(kept) == len(index.chunks):
        return index, []
    chunks = [index.chunks[i] for i in kept] + new_chunks
    old_vecs = index.vectors[kept] if kept else None
    new_vecs = np.array(embeddings.embed_documents([c.text for c in new_chunks]), dtype=np.float32) \
        if new_chunks else None
    if old_vecs is None and new_vecs is None:
        return empty_index(), changes
    vectors = new_vecs if old_vecs is None else old_vecs if new_vecs is None else np.vstack([old_vecs, new_vecs])
    return HybridIndex(chunks, vectors), changes
