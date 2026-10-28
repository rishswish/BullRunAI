"""BullRun MCP server: exposes BullRun's market-research capabilities over the
Model Context Protocol, so any MCP client can use them.

Primitives exposed
  tools      get_quote, get_news, search_filings, compare_tickers, get_portfolio*
  resources  bullrun://filings/index  (what's in the RAG index)
             bullrun://watchlist      (demo/default user's watchlist)*
  prompts    analyze_ticker, earnings_risk_review

  * user-scoped items use MCP_USER_EMAIL (for a personal Claude Desktop setup).

Run
  python -m bullrun_agent.mcp_server                     # stdio (Claude Desktop / Cursor)
  python -m bullrun_agent.mcp_server --http --port 8765  # streamable HTTP (agent, Cloud Run)
"""
from __future__ import annotations

import argparse
import json
import os

from mcp.server.fastmcp import FastMCP

from . import data_sources as ds
from .rag import get_index
from .rag import search_filings as _search_filings

mcp = FastMCP(
    "bullrun",
    instructions=("Market research tools from BullRun: live quotes, ticker news with sentiment, and "
                  "hybrid search over SEC 10-K/10-Q filings with citations. Data marked source=demo is sample data."),
    host="0.0.0.0",
    port=int(os.environ.get("PORT", 8765)),
    stateless_http=True,  # no sticky sessions needed -> scales horizontally on Cloud Run
)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------
@mcp.tool()
def get_quote(ticker: str) -> dict:
    """Latest price, daily change %, day range and volume for a stock/ETF ticker (e.g. NVDA)."""
    return ds.get_quote(ticker)


@mcp.tool()
def get_news(ticker: str, limit: int = 5) -> dict:
    """Recent news for a ticker: title, publisher, date, description and per-article sentiment."""
    return ds.get_news(ticker, limit)


@mcp.tool()
def search_filings(query: str, ticker: str | None = None, form: str | None = None) -> dict:
    """Hybrid (BM25 + embedding) search over SEC 10-K/10-Q filings. Optional ticker and form
    ('10-K'/'10-Q') filters. Each result has a source_id (S1..) and a citation with the EDGAR URL."""
    return _search_filings(query, ticker=ticker, form=form)


@mcp.tool()
def compare_tickers(tickers: list[str]) -> dict:
    """Side-by-side quote comparison for 2-6 tickers, sorted by daily % change."""
    rows = [ds.get_quote(t) for t in tickers[:6]]
    ok = [r for r in rows if "error" not in r]
    ok.sort(key=lambda r: r.get("change_pct") or 0, reverse=True)
    return {"comparison": ok, "errors": [r for r in rows if "error" in r]}


@mcp.tool()
def get_portfolio() -> dict:
    """Holdings for the configured BullRun user (MCP_USER_EMAIL), with weights and P/L."""
    return ds.get_portfolio(os.environ.get("MCP_USER_EMAIL", "demo@bullrun.ai"))


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------
@mcp.resource("bullrun://filings/index")
def filings_index() -> str:
    """Which companies and filings are searchable."""
    idx = get_index()
    if not idx:
        return json.dumps({"tickers": [], "note": "index not built"})
    seen = {}
    for c in idx.chunks:
        m = c.meta
        seen.setdefault((m["ticker"], m["form"], m["filed"]), m.get("url"))
    return json.dumps({"tickers": idx.tickers, "chunks": len(idx.chunks),
                       "filings": [{"ticker": t, "form": f, "filed": d, "url": u} for (t, f, d), u in seen.items()]})


@mcp.resource("bullrun://watchlist")
def watchlist() -> str:
    """The configured user's watchlist."""
    email = os.environ.get("MCP_USER_EMAIL", "demo@bullrun.ai")
    return json.dumps(ds.get_user_store().get_user(email).get("watchlist", []))


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------
@mcp.prompt()
def analyze_ticker(ticker: str) -> str:
    """One-page research brief on a ticker using quotes, news and filings."""
    return (f"Write a concise research brief on {ticker.upper()}.\n"
            f"1. Call get_quote and get_news for {ticker.upper()}.\n"
            f"2. Call search_filings for its top risk factors and for management's outlook.\n"
            "3. Structure: Snapshot | What's moving it | Key risks (cite [S#]) | What to watch.\n"
            "Ground every number in tool output. Educational, not investment advice.")


@mcp.prompt()
def earnings_risk_review(ticker: str) -> str:
    """Pre-earnings checklist built from the latest filing."""
    return (f"Before {ticker.upper()} reports, use search_filings to pull (a) segment revenue trends, "
            "(b) the newest or expanded risk factors, (c) liquidity/capex commentary. "
            "Summarize as a checklist of 5-7 items to watch on the call, each with a citation.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--http", action="store_true", help="serve streamable HTTP instead of stdio")
    ap.add_argument("--port", type=int, default=None)
    args = ap.parse_args()
    if args.port:
        mcp.settings.port = args.port
    mcp.run(transport="streamable-http" if args.http else "stdio")


if __name__ == "__main__":
    main()
