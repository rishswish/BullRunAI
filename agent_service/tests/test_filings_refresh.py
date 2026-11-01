"""Index refresh: only new filings are embedded, superseded ones are dropped, and a
company nobody asked about before is indexed on demand."""
import pytest

from bullrun_agent import rag
from bullrun_agent.config import get_settings
from bullrun_agent.llm import HashEmbeddings
from bullrun_agent.rag import updater
from bullrun_agent.rag.edgar import Filing

from .conftest import FAKE_10K


class CountingEmbeddings(HashEmbeddings):
    calls = 0

    def embed_documents(self, texts):
        CountingEmbeddings.calls += len(texts)
        return super().embed_documents(texts)


def filing(form, filed, ticker="ACME"):
    return Filing(ticker=ticker, company="Acme Chips", cik=1, form=form, filed=filed, period=filed,
                  url=f"https://sec.example/{ticker}-{form}-{filed}.htm")


@pytest.fixture
def edgar(monkeypatch):
    """A fake EDGAR whose filing list each test can change."""
    state = {"filings": [filing("10-Q", "2026-07-30"), filing("10-K", "2026-02-20")], "broken": set()}

    def fake_list(ticker, forms=("10-K", "10-Q"), limit=12):
        return [f for f in state["filings"] if f.ticker == ticker.upper()]

    def fake_fetch(f):
        if f.url in state["broken"]:
            raise RuntimeError("EDGAR timeout")
        f.text = FAKE_10K
        return f

    monkeypatch.setattr(updater, "list_filings", fake_list)
    monkeypatch.setattr(updater, "fetch_text", fake_fetch)
    CountingEmbeddings.calls = 0
    return state


def urls(index):
    return {c.meta["url"].rsplit("/", 1)[1] for c in index.chunks}


def test_first_run_indexes_latest_10k_and_10q(edgar):
    index, changes = updater.refresh(None, ["ACME"], CountingEmbeddings())
    assert urls(index) == {"ACME-10-Q-2026-07-30.htm", "ACME-10-K-2026-02-20.htm"}
    assert len(changes) == 2 and CountingEmbeddings.calls == len(index.chunks)


def test_nothing_new_means_nothing_embedded(edgar):
    index, _ = updater.refresh(None, ["ACME"], CountingEmbeddings())
    CountingEmbeddings.calls = 0
    same, changes = updater.refresh(index, ["ACME"], CountingEmbeddings())
    assert changes == [] and same is index and CountingEmbeddings.calls == 0


def test_new_10q_replaces_old_one_and_keeps_the_10k(edgar):
    index, _ = updater.refresh(None, ["ACME"], CountingEmbeddings())
    edgar["filings"].insert(0, filing("10-Q", "2026-10-29"))  # Acme files its next quarter
    CountingEmbeddings.calls = 0
    index2, changes = updater.refresh(index, ["ACME"], CountingEmbeddings())
    assert urls(index2) == {"ACME-10-Q-2026-10-29.htm", "ACME-10-K-2026-02-20.htm"}
    assert any("added ACME 10-Q filed 2026-10-29" in c for c in changes)
    assert any("dropped ACME 10-Q filed 2026-07-30" in c for c in changes)
    assert CountingEmbeddings.calls == len([c for c in index2.chunks if c.meta["filed"] == "2026-10-29"])
    assert index2.search("foundries supply constraints", HashEmbeddings(), ticker="ACME")


def test_old_filing_stays_if_the_new_one_cannot_be_fetched(edgar):
    index, _ = updater.refresh(None, ["ACME"], CountingEmbeddings())
    new = filing("10-Q", "2026-10-29")
    edgar["filings"].insert(0, new)
    edgar["broken"].add(new.url)
    index2, _ = updater.refresh(index, ["ACME"], CountingEmbeddings())
    assert "ACME-10-Q-2026-07-30.htm" in urls(index2)


def test_other_companies_are_left_alone(edgar):
    index, _ = updater.refresh(None, ["ACME"], CountingEmbeddings())
    edgar["filings"].append(filing("10-K", "2026-03-01", ticker="BETA"))
    index2, _ = updater.refresh(index, ["BETA"], CountingEmbeddings())
    assert {"ACME", "BETA"} <= set(index2.tickers)


def test_unindexed_company_is_fetched_on_first_question(edgar, monkeypatch, tmp_path):
    s = get_settings()
    monkeypatch.setattr(s, "on_demand_filings", True)
    monkeypatch.setattr(s, "index_dir", tmp_path)
    monkeypatch.setattr(s, "index_gcs_uri", None)
    monkeypatch.setattr("bullrun_agent.rag.edgar.ticker_map", lambda: {"ACME": (1, "Acme Chips")})
    monkeypatch.setattr(rag, "_embedder", CountingEmbeddings)
    rag.set_index(None)
    try:
        out = rag.search_filings("export controls", ticker="ACME")
        assert out["results"] and "just now" in out["note"]
        assert (tmp_path / "chunks.jsonl").exists()  # published for other instances

        etf = rag.search_filings("risks", ticker="SPY")  # not an SEC filer
        assert etf["results"] == [] and "ETF" in etf["note"]
    finally:
        rag.set_index(None)
