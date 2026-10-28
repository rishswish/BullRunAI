"""Download 10-K / 10-Q filings from SEC EDGAR (free, no API key).

SEC asks every client to send a descriptive User-Agent with a contact email and
to stay under 10 requests/second - set SEC_USER_AGENT in your .env.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from functools import lru_cache

import httpx
from bs4 import BeautifulSoup

from ..config import get_settings

log = logging.getLogger(__name__)

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"


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
        acc = recent["accessionNumber"][i].replace("-", "")
        out.append(Filing(ticker=ticker.upper(), company=company, cik=cik, form=form,
                          filed=recent["filingDate"][i], period=recent["reportDate"][i],
                          url=ARCHIVE_URL.format(cik=cik, acc=acc, doc=recent["primaryDocument"][i])))
        if len(out) >= limit:
            break
    return out


def fetch_text(filing: Filing) -> Filing:
    with _client() as c:
        html = c.get(filing.url).text
    time.sleep(0.2)  # be polite to EDGAR
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style"]):
        tag.decompose()
    # Inline XBRL hides machine-readable facts in <ix:header>; drop it.
    for tag in soup.find_all(re.compile(r"^ix:header$")):
        tag.decompose()
    text = soup.get_text("\n")
    text = re.sub(r"\xa0", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    filing.text = text.strip()
    log.info("fetched %s %s %s (%d chars)", filing.ticker, filing.form, filing.filed, len(filing.text))
    return filing
