"""LangChain tools the agent can call.

Two families:
  * public-data tools (quotes, news, filings) - stateless, also served by the MCP
    server so any MCP client (Claude Desktop, Cursor, the agent itself) can use them;
  * user-scoped tools (portfolio, watchlist) - always in-process, because they need
    the authenticated user's identity, which arrives via RunnableConfig and is never
    something the model can choose or spoof through tool arguments.

`update_watchlist` writes data, so it pauses the graph with `interrupt()` and only
proceeds once the user approves in the UI (human-in-the-loop).
"""
from __future__ import annotations

import json
import re
from typing import Annotated

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, tool
from langgraph.types import interrupt

from . import data_sources as ds
from .rag import search_filings as _search_filings

TICKER_RE = re.compile(r"^[A-Z]{1,5}(\.[A-Z])?$")


def _j(obj) -> str:
    return json.dumps(obj, default=str)


def _user(config: RunnableConfig) -> str:
    email = (config or {}).get("configurable", {}).get("user_email")
    if not email:
        raise ValueError("No authenticated user in context")
    return email


def _clean(tickers: list[str]) -> list[str]:
    out = []
    for t in tickers or []:
        t = t.upper().strip().lstrip("$")
        if TICKER_RE.match(t) and t not in out:
            out.append(t)
    return out


# ---------------------------------------------------------------------------
# Public-data tools
# ---------------------------------------------------------------------------
@tool
def get_quote(ticker: Annotated[str, "Stock or ETF symbol, e.g. NVDA"]) -> str:
    """Latest price, daily change %, day range and volume for one ticker.
    Call once per ticker; call several in parallel to compare tickers."""
    return _j(ds.get_quote(ticker))


@tool
def get_news(ticker: Annotated[str, "Stock symbol"], limit: Annotated[int, "1-10"] = 5) -> str:
    """Recent news headlines for a ticker with publisher, date and per-article sentiment.
    Use to explain *why* a stock moved or what the market is talking about."""
    return _j(ds.get_news(ticker, limit))


@tool
def search_filings(query: Annotated[str, "What to look for, phrased as a question or keywords"],
                   ticker: Annotated[str | None, "Restrict to one company's filings"] = None,
                   form: Annotated[str | None, "'10-K' or '10-Q'"] = None) -> str:
    """Search the company's SEC 10-K/10-Q filings (risk factors, MD&A, business description,
    guidance, segment data). Returns passages with source ids S1..Sn - cite them as [S1]."""
    return _j(_search_filings(query, ticker=ticker, form=form))


PUBLIC_TOOLS: list[BaseTool] = [get_quote, get_news, search_filings]


# ---------------------------------------------------------------------------
# User-scoped tools
# ---------------------------------------------------------------------------
@tool
def get_portfolio(config: RunnableConfig) -> str:
    """The signed-in user's holdings: positions, market values, weights, unrealized P/L,
    day change and their watchlist. Use for any question about 'my portfolio / holdings'."""
    return _j(ds.get_portfolio(_user(config)))


def apply_watchlist_change(email: str, add: list[str], remove: list[str]) -> dict:
    current = ds.get_user_store().get_user(email).get("watchlist", [])
    new = [t for t in current if t not in remove] + [t for t in add if t not in current]
    ds.get_user_store().set_watchlist(email, new)
    return {"watchlist": new, "added": [t for t in add if t not in current],
            "removed": [t for t in remove if t in current]}


@tool
def update_watchlist(config: RunnableConfig,
                     add: Annotated[list[str], "Tickers to add"] = [],  # noqa: B006
                     remove: Annotated[list[str], "Tickers to remove"] = []) -> str:  # noqa: B006
    """Add or remove tickers on the user's watchlist. Call it directly for any watchlist edit;
    it merges with the saved list (duplicates are ignored) and the user approves first."""
    email = _user(config)
    add, remove = _clean(add), _clean(remove)
    if not add and not remove:
        return _j({"error": "No valid tickers given"})
    decision = interrupt({"type": "approve_watchlist", "add": add, "remove": remove,
                          "message": f"Update watchlist: +{add or '[]'} -{remove or '[]'}?"})
    if not (isinstance(decision, dict) and decision.get("approved")):
        return _j({"status": "cancelled", "reason": "User declined the change"})
    return _j({"status": "applied", **apply_watchlist_change(email, add, remove)})


USER_TOOLS: list[BaseTool] = [get_portfolio, update_watchlist]


async def load_tools(mode: str = "local", mcp_url: str | None = None) -> list[BaseTool]:
    """Local mode: all tools in-process. MCP mode: public tools fetched from the
    BullRun MCP server over streamable HTTP; user tools stay local."""
    if mode == "mcp":
        from langchain_mcp_adapters.client import MultiServerMCPClient

        client = MultiServerMCPClient({"bullrun": {"url": mcp_url, "transport": "streamable_http"}})
        local_names = {t.name for t in USER_TOOLS}
        # User-scoped tools always run in-process (they need the authenticated identity).
        public = [t for t in await client.get_tools() if t.name not in local_names]
        return [*public, *USER_TOOLS]
    return [*PUBLIC_TOOLS, *USER_TOOLS]
