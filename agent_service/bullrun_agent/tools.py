"""LangChain tools the agent can call.

Two families:
  * public-data tools (quotes, news, filings) - stateless, also served by the MCP
    server so any MCP client (Claude Desktop, Cursor, the agent itself) can use them;
  * user-scoped tools (portfolio, watchlist) - always in-process, because they need
    the authenticated user's identity, which arrives via RunnableConfig and is never
    something the model can choose or spoof through tool arguments.

`update_watchlist` and `update_holdings` write data, so they pause the graph with
`interrupt()` and only proceed once the user approves in the UI (human-in-the-loop).
"""
from __future__ import annotations

import json
import re
from typing import Annotated

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, tool
from langgraph.types import interrupt
from pydantic import BaseModel, Field

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
    """Recent news about a company from two providers, filtered to articles that actually
    mention it and ranked headline-first. Sentiment is included only for stories about the stock.
    Use to explain *why* a stock moved or what the market is talking about."""
    return _j(ds.get_news(ticker, limit))


@tool
def search_filings(query: Annotated[str, "What to look for, phrased as a question or keywords"],
                   ticker: Annotated[str | None, "Restrict to one company's filings"] = None,
                   form: Annotated[str | None, "'10-K' or '10-Q'"] = None) -> str:
    """Search a company's latest SEC 10-K and 10-Q (risk factors, MD&A, business description,
    guidance, segment data). Works for any US-listed company: one not searched before is
    fetched from EDGAR on the spot. Returns passages with source ids (S1, S2...) - cite them as [S1].
    Ids keep counting across searches in one answer, so always use the ids as returned."""
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


def _num(x: float) -> float | int:
    return int(x) if float(x).is_integer() else round(x, 4)


class Trade(BaseModel):
    symbol: str = Field(description="Ticker bought or sold, e.g. NVDA")
    shares: float = Field(description="Shares traded: positive if bought, negative if sold")
    price: float | None = Field(None, description="Price per share paid/received, if the user said")


def plan_holdings_change(email: str, trades: list[dict]) -> dict:
    """Work out trades against the user's manual holdings without saving anything.
    Returns {"error": ...} or the before/after of each position, for the user to approve."""
    if not trades:
        return {"error": "No trades given"}
    user = ds.get_user_store().get_user(email)
    if user.get("snaptrade_user_id"):
        return {"error": "This account's holdings come from a connected brokerage and update from there; "
                         "they can't be edited by hand."}
    holdings = [dict(h) for h in user.get("manual_holdings") or []]
    changes = []
    for t in trades:
        symbol, shares, price = t.get("symbol", ""), float(t.get("shares") or 0), t.get("price")
        sym = (_clean([symbol]) or [None])[0]
        if not sym:
            return {"error": f"'{symbol}' is not a valid ticker"}
        if not shares or abs(shares) > 1e7:
            return {"error": f"Give a non-zero number of {sym} shares (positive = bought, negative = sold)"}
        if price is not None and price <= 0:
            return {"error": "Price per share must be positive"}
        price_source = "given"
        if price is None:
            q = ds.get_quote(sym)
            if not q.get("price") or q.get("source") in ("none", None):
                return {"error": f"Couldn't get a current price for {sym}; ask the user what they paid per share"}
            price, price_source = float(q["price"]), "current price"

        pos = next((h for h in holdings if h["symbol"] == sym), None)
        qty = float(pos["quantity"]) if pos else 0.0
        avg = pos.get("avgCost") if pos else None
        before = {"quantity": _num(qty), "avgCost": avg} if pos else None
        if shares > 0:
            new_qty = qty + shares
            # weighted average cost; stays unknown if the old position had none
            new_avg = price if qty == 0 else (qty * avg + shares * price) / new_qty if avg else None
        else:
            if abs(shares) > qty + 1e-9:
                return {"error": f"The user holds {_num(qty)} {sym} in manual holdings, so can't sell {_num(-shares)}"}
            new_qty, new_avg = qty + shares, avg  # selling doesn't change what the rest cost
        if pos is None and len(holdings) >= 50:
            return {"error": "Manual holdings are limited to 50 positions"}

        after = None if new_qty <= 1e-9 else {"quantity": _num(new_qty),
                                              "avgCost": round(new_avg, 4) if new_avg else None}
        if pos is None:
            holdings.append({"symbol": sym, **after})
        elif after is None:
            holdings.remove(pos)
        else:
            pos.update(after)
        changes.append({"symbol": sym, "action": "buy" if shares > 0 else "sell", "shares": _num(abs(shares)),
                        "price": round(price, 4), "price_source": price_source, "before": before, "after": after})
    return {"changes": changes, "holdings": holdings}


@tool
def update_holdings(config: RunnableConfig,
                    trades: Annotated[list[Trade], "One entry per stock bought or sold"]) -> str:
    """Record trades the user says they made ("I bought 10 more NVDA", "sold 5 TSLA at 250",
    "bought 10 NVDA and 10 TSLA") in their manually entered holdings. Updates share counts and
    average cost; with no price, the current market price is used. Put all trades from one message
    in a single call. Call it directly; the user approves before anything is saved. Cash is not changed."""
    email = _user(config)
    plan = plan_holdings_change(email, [t.model_dump() if isinstance(t, BaseModel) else dict(t) for t in trades])
    if plan.get("error"):
        return _j(plan)
    holdings = plan.pop("holdings")
    lines = [f"{'Bought' if c['action'] == 'buy' else 'Sold'} {c['shares']} {c['symbol']} at ${c['price']:,.2f}"
             for c in plan["changes"]]
    decision = interrupt({"type": "approve_holdings", **plan, "message": "; ".join(lines) + "?"})
    if not (isinstance(decision, dict) and decision.get("approved")):
        return _j({"status": "cancelled", "reason": "User declined the change"})
    ds.get_user_store().set_manual_holdings(email, holdings)
    return _j({"status": "applied", **plan, "note": "Cash balance was not changed."})


USER_TOOLS: list[BaseTool] = [get_portfolio, update_watchlist, update_holdings]


async def load_tools(mode: str = "local", mcp_url: str | None = None) -> list[BaseTool]:
    """Local mode: all tools in-process. MCP mode: public tools fetched from the
    BullRun MCP server over streamable HTTP; user tools stay local."""
    if mode == "mcp":
        from langchain_mcp_adapters.client import MultiServerMCPClient

        from .config import get_settings

        conn = {"url": mcp_url, "transport": "streamable_http"}
        if secret := get_settings().session_secret:  # the MCP server requires a token once OAuth is on
            from .mcp_auth import service_token

            conn["headers"] = {"Authorization": f"Bearer {service_token(secret)}"}
        client = MultiServerMCPClient({"bullrun": conn})
        # account tools always run in-process with the chat's own user, never via the MCP server
        local_names = {t.name for t in USER_TOOLS} | {"get_watchlist"}
        # User-scoped tools always run in-process (they need the authenticated identity).
        public = [t for t in await client.get_tools() if t.name not in local_names]
        return [*public, *USER_TOOLS]
    return [*PUBLIC_TOOLS, *USER_TOOLS]
