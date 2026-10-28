"""Raw data access: Polygon market data, Firestore user store, SnapTrade holdings.

Each function returns plain dicts and falls back to bundled demo data when the
relevant credentials are missing, so the agent always has something real-shaped
to reason over. Results carry `"source": "polygon" | "demo" | ...` so the model
(and the UI) can be honest about where numbers came from.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from typing import Any, Protocol

import httpx

from .config import PACKAGE_DIR, Settings, get_settings

log = logging.getLogger(__name__)


@lru_cache
def demo_data() -> dict:
    return json.loads((PACKAGE_DIR / "data" / "demo_data.json").read_text())


# ---------------------------------------------------------------------------
# Tiny TTL cache so repeated tool calls inside one conversation don't burn
# Polygon's free-tier rate limit (5 req/min).
# ---------------------------------------------------------------------------
_cache: dict[str, tuple[float, Any]] = {}
_cache_lock = threading.Lock()


def _cached(key: str, ttl: float, fn):
    now = time.time()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
    val = fn()
    with _cache_lock:
        _cache[key] = (now, val)
    return val


# ---------------------------------------------------------------------------
# Market data
# ---------------------------------------------------------------------------
def _polygon_get(path: str, params: dict | None, s: Settings) -> dict:
    p = dict(params or {})
    p["apiKey"] = s.polygon_api_key
    r = httpx.get(f"{s.polygon_base_url}{path}", params=p, timeout=10)
    r.raise_for_status()
    return r.json()


def get_quote(ticker: str, settings: Settings | None = None) -> dict:
    s = settings or get_settings()
    t = ticker.upper().strip()
    if s.demo_market:
        q = demo_data()["quotes"].get(t)
        if not q:
            return {"ticker": t, "error": f"No demo data for {t}. Demo tickers: {', '.join(demo_data()['quotes'])}",
                    "source": "demo"}
        return _shape_quote(t, q, source="demo")

    def fetch():
        # One call for the last two daily bars -> latest session + previous close.
        end = date.today()
        bars = _polygon_get(f"/v2/aggs/ticker/{t}/range/1/day/{end - timedelta(days=10)}/{end}",
                            {"adjusted": "true", "sort": "desc", "limit": 2}, s).get("results") or []
        if not bars:
            return {"ticker": t, "error": "Ticker not found or no recent trading data", "source": "polygon"}
        cur = bars[0]
        prev_close = bars[1]["c"] if len(bars) > 1 else cur["o"]
        try:
            name = _cached(f"name:{t}", 86400, lambda: _polygon_get(
                f"/v3/reference/tickers/{t}", None, s).get("results", {}).get("name", t))
        except Exception:  # reference lookup is best-effort
            name = t
        as_of = datetime.fromtimestamp(cur["t"] / 1000, tz=timezone.utc).date().isoformat()
        return _shape_quote(t, {"name": name, "close": cur["c"], "open": cur["o"], "high": cur["h"],
                                "low": cur["l"], "prev_close": prev_close, "volume": cur["v"]},
                            source="polygon", as_of=as_of)

    try:
        return _cached(f"quote:{t}", 60, fetch)
    except httpx.HTTPError as e:
        log.warning("polygon quote failed for %s: %s", t, e)
        return {"ticker": t, "error": f"market data unavailable ({e.__class__.__name__})", "source": "polygon"}


def _shape_quote(t: str, q: dict, source: str, as_of: Any = None) -> dict:
    change = q["close"] - q["prev_close"]
    return {
        "ticker": t,
        "name": q.get("name", t),
        "price": round(q["close"], 2),
        "change": round(change, 2),
        "change_pct": round(100 * change / q["prev_close"], 2) if q["prev_close"] else None,
        "day_range": [q["low"], q["high"]],
        "volume": q.get("volume"),
        "as_of": as_of,
        "source": source,
    }


def get_news(ticker: str, limit: int = 5, settings: Settings | None = None) -> dict:
    s = settings or get_settings()
    t = ticker.upper().strip()
    limit = max(1, min(int(limit), 10))
    if s.demo_market:
        items = demo_data()["news"].get(t, [])[:limit]
        return {"ticker": t, "articles": items, "source": "demo"}

    def fetch():
        data = _polygon_get("/v2/reference/news", {"ticker": t, "limit": limit, "order": "desc"}, s)
        arts = []
        for a in data.get("results", []):
            ins = next((i for i in a.get("insights") or [] if i.get("ticker") == t), {})
            arts.append({
                "title": a.get("title"),
                "publisher": (a.get("publisher") or {}).get("name"),
                "published_utc": a.get("published_utc"),
                "description": (a.get("description") or "")[:400],
                "sentiment": ins.get("sentiment"),
                "url": a.get("article_url"),
            })
        return {"ticker": t, "articles": arts, "source": "polygon"}

    try:
        return _cached(f"news:{t}:{limit}", 300, fetch)
    except httpx.HTTPError as e:
        log.warning("polygon news failed for %s: %s", t, e)
        return {"ticker": t, "articles": [], "error": "news unavailable", "source": "polygon"}


# ---------------------------------------------------------------------------
# User store (watchlist + SnapTrade credentials)
# ---------------------------------------------------------------------------
class UserStore(Protocol):
    def get_user(self, email: str) -> dict: ...
    def set_watchlist(self, email: str, tickers: list[str]) -> list[str]: ...


class DemoUserStore:
    """In-memory store seeded from demo_data.json (per-process, resets on restart)."""

    def __init__(self):
        self._users: dict[str, dict] = {}
        self._lock = threading.Lock()

    def get_user(self, email: str) -> dict:
        with self._lock:
            return self._users.setdefault(email, {"email": email, "watchlist": list(demo_data()["watchlist"])})

    def set_watchlist(self, email: str, tickers: list[str]) -> list[str]:
        user = self.get_user(email)
        with self._lock:
            user["watchlist"] = tickers
        return tickers


class FirestoreUserStore:
    """Reads/writes the same `users/{email}` docs as the Flask server."""

    def __init__(self, s: Settings):
        from google.cloud import firestore
        from google.oauth2 import service_account

        creds = service_account.Credentials.from_service_account_info(json.loads(s.firebase_service_account))
        self.db = firestore.Client(credentials=creds, project=s.project_id, database=s.firestore_database)

    def get_user(self, email: str) -> dict:
        snap = self.db.collection("users").document(email).get()
        return snap.to_dict() or {"email": email, "watchlist": []}

    def set_watchlist(self, email: str, tickers: list[str]) -> list[str]:
        self.db.collection("users").document(email).set({"watchlist": tickers}, merge=True)
        return tickers


@lru_cache
def get_user_store() -> UserStore:
    s = get_settings()
    if s.demo_portfolio:
        return DemoUserStore()
    return FirestoreUserStore(s)


# ---------------------------------------------------------------------------
# Portfolio
# ---------------------------------------------------------------------------
def get_portfolio(email: str, settings: Settings | None = None) -> dict:
    s = settings or get_settings()
    user = get_user_store().get_user(email)
    holdings = None
    if user.get("snaptrade_user_id") and user.get("snaptrade_user_secret"):
        holdings = _snaptrade_positions(user["snaptrade_user_id"], user["snaptrade_user_secret"])
    if holdings is None:
        holdings = demo_data()["portfolio"]

    positions = []
    total = 0.0
    for p in holdings["positions"]:
        q = get_quote(p["symbol"], s)
        price = q.get("price") or p.get("price") or p.get("avgCost") or 0
        mv = p.get("marketValue") or price * float(p.get("quantity") or 0)
        total += mv
        pos = {"symbol": p["symbol"], "name": p.get("name"), "quantity": p.get("quantity"),
               "price": price, "market_value": round(mv, 2), "day_change_pct": q.get("change_pct")}
        if p.get("avgCost"):
            pos["unrealized_pl_pct"] = round(100 * (price - p["avgCost"]) / p["avgCost"], 2)
        positions.append(pos)
    for pos in positions:
        pos["weight_pct"] = round(100 * pos["market_value"] / total, 2) if total else 0
    positions.sort(key=lambda x: x["market_value"], reverse=True)
    return {
        "source": holdings.get("source", "snaptrade"),
        "total_invested": round(total, 2),
        "cash": holdings.get("totals", {}).get("totalBalance"),
        "positions": positions,
        "concentration_top1_pct": positions[0]["weight_pct"] if positions else 0,
        "watchlist": user.get("watchlist", []),
    }


def _snaptrade_positions(uid: str, secret: str) -> dict | None:
    s = get_settings()
    import os

    key, cid = os.environ.get("SNAPTRADE_CONSUMER_KEY"), os.environ.get("SNAPTRADE_CLIENT_ID")
    if not (key and cid):
        return None
    try:
        from snaptrade_client import SnapTrade

        st = SnapTrade(consumer_key=key, client_id=cid)
        positions, cash = [], 0.0
        for acct in st.account_information.list_user_accounts(user_id=uid, user_secret=secret).body or []:
            aid = acct.get("id")
            for p in st.account_information.get_user_account_positions(
                    user_id=uid, user_secret=secret, account_id=aid).body or []:
                sym = ((p.get("symbol") or {}).get("symbol") or {})
                ticker = sym.get("symbol") if isinstance(sym, dict) else sym
                if ticker:
                    name = sym.get("description") if isinstance(sym, dict) else None
                    positions.append({"symbol": ticker, "name": name,
                                      "quantity": p.get("units"), "price": p.get("price"),
                                      "avgCost": p.get("average_purchase_price")})
        return {"source": "snaptrade", "positions": positions, "totals": {"totalBalance": cash}}
    except Exception as e:  # never let brokerage hiccups break the chat
        log.warning("snaptrade fetch failed: %s (settings demo=%s)", e, s.demo_portfolio)
        return None
