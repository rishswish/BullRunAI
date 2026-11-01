"""BullRun MCP server: exposes BullRun's market-research capabilities over the
Model Context Protocol, so any MCP client can use them.

Primitives exposed
  tools      get_quote, get_news, search_filings, compare_tickers,
             get_portfolio*, get_watchlist*, update_watchlist*
  resources  bullrun://filings/index  (what's in the RAG index)
             bullrun://watchlist      (the user's watchlist)*
  prompts    analyze_ticker, earnings_risk_review

  * user-scoped: over HTTP with OAuth on (MCP_PUBLIC_URL, SESSION_SECRET, GOOGLE_CLIENT_ID,
    GOOGLE_OAUTH_CLIENT_SECRET) they act on the user who signed in with Google; locally over
    stdio they use MCP_USER_EMAIL (a personal Claude Desktop setup).

Run
  python -m bullrun_agent.mcp_server                     # stdio (Claude Desktop / Cursor)
  python -m bullrun_agent.mcp_server --http --port 8765  # streamable HTTP (agent, Cloud Run)
"""
from __future__ import annotations

import argparse
import json
import os

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse

from . import data_sources as ds
from .config import get_settings
from .mcp_auth import SCOPE, FirestoreClients, GoogleOAuthProvider, MemoryClients
from .rag import get_index
from .rag import search_filings as _search_filings


def _oauth_provider() -> GoogleOAuthProvider | None:
    s = get_settings()
    if not (s.mcp_public_url and s.session_secret and s.google_client_id and s.google_oauth_client_secret):
        return None
    store = ds.get_user_store()
    clients = FirestoreClients(store.db) if hasattr(store, "db") else MemoryClients()
    return GoogleOAuthProvider(public_url=s.mcp_public_url, secret=s.session_secret,
                               google_client_id=s.google_client_id,
                               google_client_secret=s.google_oauth_client_secret, clients=clients,
                               on_connect=ds.get_user_store().mark_mcp_connected)


oauth = _oauth_provider()
mcp = FastMCP(
    "bullrun",
    auth_server_provider=oauth,
    auth=AuthSettings(
        issuer_url=oauth.public_url, resource_server_url=f"{oauth.public_url}/mcp", required_scopes=[SCOPE],
        client_registration_options=ClientRegistrationOptions(enabled=True, valid_scopes=[SCOPE],
                                                              default_scopes=[SCOPE]),
        validate_token_resource=False,  # tokens are our own signed JWTs
    ) if oauth else None,
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


def _user_email() -> str:
    """Who the account tools act on: the OAuth-signed-in user, or MCP_USER_EMAIL for local stdio."""
    tok = get_access_token()
    if tok is not None:
        if not tok.subject:
            raise ValueError("This connection isn't signed in to a BullRun account.")
        return tok.subject
    if oauth is not None:  # never fall back to a default user on the public server
        raise ValueError("Sign in to BullRun to use account tools.")
    return os.environ.get("MCP_USER_EMAIL", "demo@bullrun.ai")


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def get_portfolio() -> dict:
    """The signed-in user's BullRun holdings (manual and linked accounts) with weights, P/L and cash."""
    return ds.get_portfolio(_user_email())


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def get_watchlist() -> dict:
    """Tickers on the signed-in user's BullRun watchlist."""
    return {"watchlist": ds.get_user_store().get_user(_user_email()).get("watchlist", [])}


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True))
def update_watchlist(add: list[str] | None = None, remove: list[str] | None = None) -> dict:
    """Add or remove tickers on the signed-in user's BullRun watchlist (shows up on their dashboard).
    Confirm the change with the user before calling."""
    from .tools import _clean, apply_watchlist_change

    add, remove = _clean(add or []), _clean(remove or [])
    if not add and not remove:
        return {"error": "No valid tickers given"}
    return {"status": "applied", **apply_watchlist_change(_user_email(), add, remove)}


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
    return json.dumps(ds.get_user_store().get_user(_user_email()).get("watchlist", []))


# ---------------------------------------------------------------------------
# Google sign-in callback for the OAuth flow
# ---------------------------------------------------------------------------
if oauth is not None:
    @mcp.custom_route("/oauth/google/callback", methods=["GET"])
    async def google_callback(request: Request):
        q = request.query_params
        if q.get("error") or not q.get("code"):
            return HTMLResponse("Google sign-in was cancelled. You can close this tab.", status_code=400)
        try:
            email = await oauth.google_email(q["code"])
            return RedirectResponse(oauth.finish_authorization(q.get("state", ""), email), status_code=302)
        except Exception as e:
            return HTMLResponse(f"Sign-in failed: {e}. Please try connecting again.", status_code=400)


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
