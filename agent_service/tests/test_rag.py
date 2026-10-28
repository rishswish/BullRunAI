from bullrun_agent.llm import HashEmbeddings
from bullrun_agent.rag import search_filings
from bullrun_agent.rag.chunking import split_sections
from bullrun_agent.rag.store import HybridIndex

from .conftest import FAKE_10K


def test_sections_skip_table_of_contents():
    sections = dict(split_sections(FAKE_10K))
    assert "1A" in sections and "foundries" in sections["1A"]
    # The TOC line "Item 1A. Risk Factors" alone must not win over the real section.
    assert len(sections["1A"]) > 200


def test_chunks_carry_section_metadata(fake_index):
    sections = {c.meta["section"] for c in fake_index.chunks}
    assert {"Business", "Risk Factors", "Management's Discussion and Analysis"} <= sections
    assert all(c.text.startswith("[ACME 10-K") for c in fake_index.chunks)
    assert not any(c.meta["item"] == "9" for c in fake_index.chunks), "boilerplate items are skipped"


def test_hybrid_search_finds_risk_passage(fake_index):
    hits = fake_index.search("export controls on advanced chips", HashEmbeddings(), k=3, ticker="ACME")
    assert hits and "export controls" in hits[0].text.lower()
    assert hits[0].meta["section"] == "Risk Factors"
    assert hits[0].bm25_rank is not None and hits[0].dense_rank is not None


def test_ticker_filter_excludes_other_companies(fake_index):
    assert fake_index.search("data center revenue", HashEmbeddings(), ticker="ZZZZ") == []


def test_save_load_roundtrip(fake_index, tmp_path):
    fake_index.save(tmp_path)
    again = HybridIndex.load(tmp_path)
    assert len(again.chunks) == len(fake_index.chunks)
    assert again.tickers == ["ACME"]


def test_tool_payload_has_citations(fake_index):
    out = search_filings("foundry supply constraints", ticker="ACME")
    first = out["results"][0]
    assert first["source_id"] == "S1"
    assert first["citation"]["url"] == "https://example.com/acme-10k"


def test_missing_index_message():
    assert "not built" in search_filings("anything")["error"]
