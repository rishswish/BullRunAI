"""Download 10-K / 10-Q / 8-K filings from SEC EDGAR (free, no API key).

An 8-K's own text is often a few lines ("see Exhibit 99.1"); the substance, like an
earnings press release, is in its EX-99 exhibits, so those are fetched and appended.

SEC asks every client to send a descriptive User-Agent with a contact email and
to stay under 10 requests/second - set SEC_USER_AGENT in your .env.
"""
from __future__ import annotations

import logging
import re
import time
import warnings
from dataclasses import dataclass
from functools import lru_cache

import httpx
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

from ..config import get_settings

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)  # inline-XBRL filings

log = logging.getLogger(__name__)

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"
INDEX_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{accession}-index.htm"
MAX_EXHIBIT_CHARS = 60_000  # press releases are short; this stops a giant exhibit blowing up the index
EXHIBIT_MARK = "[[EXHIBIT {}]]"  # chunking.split_8k splits on these


@dataclass
class Filing:
    ticker: str
    company: str
    cik: int
    form: str
    filed: str
    period: str
    url: str
    text: str = ""
    items: str = ""      # 8-K item codes from EDGAR, e.g. "2.02,9.01"
    accession: str = ""  # EDGAR's id for the filing, e.g. 0001045810-26-000123


def _client() -> httpx.Client:
    return httpx.Client(headers={"User-Agent": get_settings().sec_user_agent,
                                 "Accept-Encoding": "gzip, deflate"}, timeout=30, follow_redirects=True)


@lru_cache
def ticker_map() -> dict[str, tuple[int, str]]:
    with _client() as c:
        data = c.get(TICKERS_URL).json()
    return {row["ticker"].upper(): (int(row["cik_str"]), row["title"]) for row in data.values()}


def list_filings(ticker: str, forms=("10-K", "10-Q"), limit: int = 2) -> list[Filing]:
    cik, company = ticker_map()[ticker.upper()]
    with _client() as c:
        recent = c.get(SUBMISSIONS_URL.format(cik=cik)).json()["filings"]["recent"]
    out: list[Filing] = []
    for i, form in enumerate(recent["form"]):
        if form not in forms:
            continue
        accession = recent["accessionNumber"][i]
        acc = accession.replace("-", "")
        items = recent.get("items", [""] * len(recent["form"]))[i] or ""
        out.append(Filing(ticker=ticker.upper(), company=company, cik=cik, form=form,
                          filed=recent["filingDate"][i], period=recent["reportDate"][i],
                          url=ARCHIVE_URL.format(cik=cik, acc=acc, doc=recent["primaryDocument"][i]),
                          items=items, accession=accession))
        if len(out) >= limit:
            break
    return out


def _html_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style"]):
        tag.decompose()
    # Inline XBRL hides machine-readable facts in <ix:header>; drop it.
    for tag in soup.find_all(re.compile(r"^ix:header$")):
        tag.decompose()
    text = soup.get_text("\n")
    text = re.sub(r"\xa0", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def exhibit_links(index_html: str) -> list[tuple[str, str]]:
    """[(type, url)] for the EX-99 exhibits listed on a filing's index page."""
    soup = BeautifulSoup(index_html, "lxml")
    out = []
    for row in soup.select("table.tableFile tr"):
        cells = row.find_all("td")
        link = row.find("a", href=True)
        if len(cells) < 4 or not link:
            continue
        kind = cells[3].get_text(strip=True).upper()
        href = link["href"].replace("/ix?doc=", "")
        if kind.startswith("EX-99") and href.lower().endswith((".htm", ".html", ".txt")):
            out.append((kind.removeprefix("EX-"), "https://www.sec.gov" + href if href.startswith("/") else href))
    return out[:3]


def fetch_text(filing: Filing) -> Filing:
    with _client() as c:
        text = _html_text(c.get(filing.url).text)
        time.sleep(0.2)  # be polite to EDGAR
        if filing.form == "8-K" and filing.accession:
            index = c.get(INDEX_URL.format(cik=filing.cik, acc=filing.accession.replace("-", ""),
                                           accession=filing.accession)).text
            time.sleep(0.2)
            for code, url in exhibit_links(index):
                body = _html_text(c.get(url).text)[:MAX_EXHIBIT_CHARS]
                time.sleep(0.2)
                text += f"\n\n{EXHIBIT_MARK.format(code)}\n\n{body}"
    filing.text = text
    log.info("fetched %s %s %s (%d chars)", filing.ticker, filing.form, filing.filed, len(filing.text))
    return filing
