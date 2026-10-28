from bullrun_agent.llm import HashEmbeddings
from bullrun_agent.rag import search_filings
from bullrun_agent.rag.chunking import split_sections
from bullrun_agent.rag.store import HybridIndex

from .conftest import FAKE_10K

FAKE_10Q = """
PART I. FINANCIAL INFORMATION
Item 1. Financial Statements
Revenue was 100 and costs were 60 for the quarter, compared with 90 and 55 a year earlier in the period.
Item 2. Management's Discussion and Analysis
Data center demand drove growth this quarter while gaming was flat; we expect supply to improve next quarter.
PART I. FINANCIAL INFORMATION
Item 2. Management's Discussion and Analysis (continued)
Operating expenses rose because of higher compensation and research spending across all product groups.
Item 4. Controls and Procedures
Our controls are effective and nothing changed during the quarter that would affect them materially here.
PART II. OTHER INFORMATION
Item 1A. Risk Factors
There have been no material changes to the risk factors disclosed in our annual report filed earlier this year.
Item 6. Exhibits
Exhibit list follows with certifications and other required documents for the quarterly filing period.
"""


def test_sections_skip_table_of_contents():
    sections = dict(split_sections(FAKE_10K))
    assert "foundries" in sections["Risk Factors"]
    assert len(sections["Risk Factors"]) > 200


def test_chunks_carry_section_metadata(fake_index):
    sections = {c.meta["section"] for c in fake_index.chunks}
    assert {"Business", "Risk Factors", "Management's Discussion and Analysis"} <= sections
    assert all(c.text.startswith("[ACME 10-K") for c in fake_index.chunks)
    assert not any("Accountants" in c.text for c in fake_index.chunks), "boilerplate items are skipped"


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


def test_10q_repeated_headers_keep_all_text_and_use_10q_names():
    sections = dict(split_sections(FAKE_10Q, "10-Q"))
    assert "Operating expenses" in sections["Management's Discussion and Analysis"]
    assert "Data center demand" in sections["Management's Discussion and Analysis"]
    assert "Risk Factors" in sections
    assert "Controls and Procedures" not in " ".join(sections.values())
    assert "Exhibit list" not in " ".join(sections.values())
