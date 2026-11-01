"""8-Ks: item labels, the earnings release from EX-99.1, legal boilerplate dropped, and only
recent, useful 8-Ks kept. All text here is made up."""
from datetime import date, timedelta

from bullrun_agent.rag import updater
from bullrun_agent.rag.chunking import chunk_filing, split_8k, useful_8k
from bullrun_agent.rag.edgar import EXHIBIT_MARK, Filing, exhibit_links

FAKE_8K = f"""UNITED STATES SECURITIES AND EXCHANGE COMMISSION
FORM 8-K
Acme Chips Inc.

Item 2.02 Results of Operations and Financial Condition.

On October 29, 2026, Acme Chips issued a press release announcing results for its third quarter.
A copy is attached as Exhibit 99.1.

Item 9.01 Financial Statements and Exhibits.

99.1 Press release dated October 29, 2026. SIGNATURES Pursuant to the requirements...

{EXHIBIT_MARK.format("99.1")}

Acme Chips Reports Record Third Quarter Revenue of $12.4 Billion, up 31% from a year ago.

Data center revenue was $9.1 billion, driven by demand for accelerators from cloud providers.

Forward-Looking Statements: This press release contains forward-looking statements that involve
risks and uncertainties, including supply constraints and export controls, competition and demand.
"""


def test_8k_sections_are_labelled_and_boilerplate_dropped():
    sections = dict(split_8k(FAKE_8K, "2.02,9.01"))
    assert set(sections) == {"Earnings results (Item 2.02)", "Earnings release (Ex. 99.1)"}
    release = sections["Earnings release (Ex. 99.1)"]
    assert "Record Third Quarter Revenue" in release and "forward-looking" not in release.lower()
    assert "SIGNATURES" not in "".join(sections.values())  # 9.01 is just the exhibit list


def test_two_8ks_on_one_day_get_distinct_chunk_ids():
    meta = {"ticker": "ACME", "form": "8-K", "filed": "2026-10-29", "items": "2.02,9.01"}
    a = chunk_filing(FAKE_8K, {**meta, "accession": "0000000001-26-000101"})
    b = chunk_filing(FAKE_8K, {**meta, "accession": "0000000001-26-000102"})
    assert a and not {c.id for c in a} & {c.id for c in b}
    assert a[0].text.startswith("[ACME 8-K filed 2026-10-29 | Earnings results (Item 2.02)]")


def test_vote_tallies_and_exhibit_only_8ks_are_skipped():
    assert useful_8k("2.02,9.01") and useful_8k("5.02")
    assert not useful_8k("5.07") and not useful_8k("9.01") and not useful_8k("")


def test_exhibit_links_from_the_filing_index_page():
    html = """<table class="tableFile"><tr><th>Seq</th></tr>
      <tr><td>1</td><td>8-K</td><td><a href="/ix?doc=/Archives/edgar/data/1/x/acme-8k.htm">acme-8k.htm</a></td>
          <td>8-K</td><td>1</td></tr>
      <tr><td>2</td><td>PRESS RELEASE</td><td><a href="/Archives/edgar/data/1/x/ex991.htm">ex991.htm</a></td>
          <td>EX-99.1</td><td>1</td></tr></table>"""
    assert exhibit_links(html) == [("99.1", "https://www.sec.gov/Archives/edgar/data/1/x/ex991.htm")]


def test_latest_filings_keeps_recent_useful_8ks_only(monkeypatch):
    today = date(2026, 11, 1)
    day = lambda n: (today - timedelta(days=n)).isoformat()  # noqa: E731

    def f(form, filed, items="", n=0):
        return Filing(ticker="ACME", company="Acme", cik=1, form=form, filed=filed, period=filed,
                      url=f"https://sec.example/{form}-{filed}-{n}.htm", items=items)

    filings = [f("8-K", day(3), "2.02,9.01"), f("8-K", day(5), "5.07"),  # vote tally: skipped
               *[f("8-K", day(10 + i), "8.01", i) for i in range(8)],   # more than the cap of 6
               f("10-Q", day(30)), f("8-K", day(200), "2.02"), f("10-K", day(250))]  # 8-K too old
    monkeypatch.setattr(updater, "list_filings", lambda *a, **k: filings)
    got = updater.latest_filings("ACME", today=today)
    assert [x.form for x in got].count("8-K") == updater.EIGHT_K_MAX
    assert {"10-K", "10-Q"} <= {x.form for x in got}
    assert all(x.filed >= day(updater.EIGHT_K_DAYS) for x in got if x.form == "8-K")
    assert "5.07" not in {x.items for x in got}
