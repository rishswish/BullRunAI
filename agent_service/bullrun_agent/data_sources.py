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
from zoneinfo import ZoneInfo

import httpx

from .config import PACKAGE_DIR, SERVICE_DIR, Settings, get_settings

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


class MarketDataUnavailable(Exception):
    pass


ET = ZoneInfo("America/New_York")


def _finnhub_quote(t: str, s: Settings) -> dict | None:
    """Real-time quote. None = provider error (caller falls back); {} = unknown symbol."""
    def fetch():
        r = httpx.get("https://finnhub.io/api/v1/quote", params={"symbol": t, "token": s.finnhub_api_key}, timeout=8)
        r.raise_for_status()
        return r.json()
    try:
        q = _cached(f"fh:{t}", 30, fetch)
    except httpx.HTTPError as e:
        log.warning("finnhub quote failed for %s: %s", t, e)
        return None
    if not q.get("t"):
        return {}
    as_of = datetime.fromtimestamp(q["t"], tz=ET).strftime("%Y-%m-%d %H:%M ET")
    return _shape_quote(t, {"name": t, "close": q["c"], "open": q["o"], "high": q["h"], "low": q["l"],
                            "prev_close": q["pc"]}, source="finnhub", as_of=as_of)


def _no_provider(t: str) -> dict:
    return {"ticker": t, "error": "Live market data is not configured (POLYGON_API_KEY missing).",
            "source": "none"}


def _grouped_day(day: date, s: Settings) -> dict[str, dict]:
    """Every US stock's daily bar for one date in ONE call (fits the free plan's 5 req/min).
    Cached for an hour; an empty result (holiday / not yet published) is cached too."""
    def fetch():
        data = _polygon_get(f"/v2/aggs/grouped/locale/us/market/stocks/{day.isoformat()}", {"adjusted": "true"}, s)
        return {r["T"]: r for r in data.get("results") or []}
    return _cached(f"grouped:{day}", 3600, fetch)


def _latest_two_sessions(s: Settings) -> tuple[date, dict, dict]:
    """Most recent published trading day and the one before it."""
    days: list[tuple[date, dict]] = []
    d = date.today()
    for _ in range(10):  # walk back over weekends/holidays
        bars = _grouped_day(d, s)
        if bars:
            days.append((d, bars))
            if len(days) == 2:
                return days[0][0], days[0][1], days[1][1]
        d -= timedelta(days=1)
    raise MarketDataUnavailable("no recent trading sessions returned by Polygon")


def get_quote(ticker: str, settings: Settings | None = None) -> dict:
    s = settings or get_settings()
    t = ticker.upper().strip()
    if s.demo_market:
        if not s.allow_demo_data:
            return _no_provider(t)
        q = demo_data()["quotes"].get(t)
        if not q:
            return {"ticker": t, "error": f"No demo data for {t}. Demo tickers: {', '.join(demo_data()['quotes'])}",
                    "source": "demo"}
        return _shape_quote(t, q, source="demo")

    if s.finnhub_api_key:
        q = _finnhub_quote(t, s)
        if q:
            return q
        if q == {}:
            return {"ticker": t, "error": f"No quote for {t} (check the symbol).", "source": "finnhub"}
        if not s.polygon_api_key:
            return {"ticker": t, "error": "market data unavailable", "source": "finnhub"}

    try:
        day, cur_bars, prev_bars = _latest_two_sessions(s)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 429:
            return {"ticker": t, "error": "Market data rate limit reached; try again in a minute.", "source": "polygon"}
        log.warning("polygon grouped bars failed: %s", e)
        return {"ticker": t, "error": "market data unavailable", "source": "polygon"}
    except (httpx.HTTPError, MarketDataUnavailable) as e:
        log.warning("polygon grouped bars failed: %s", e)
        return {"ticker": t, "error": "market data unavailable", "source": "polygon"}

    cur = cur_bars.get(t)
    if not cur:
        return {"ticker": t, "error": f"No trading data for {t} on {day} (check the symbol).", "source": "polygon"}
    prev = prev_bars.get(t)
    return _shape_quote(t, {"name": t, "close": cur["c"], "open": cur["o"], "high": cur["h"], "low": cur["l"],
                            "prev_close": prev["c"] if prev else cur["o"], "volume": cur.get("v")},
                        source="polygon", as_of=f"{day} close (end-of-day)")


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
        if not s.allow_demo_data:
            return {**_no_provider(t), "articles": []}
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

    if s.polygon_api_key:
        try:
            out = _cached(f"news:{t}:{limit}", 300, fetch)
            if out["articles"] or not s.finnhub_api_key:
                return out
        except httpx.HTTPError as e:
            log.warning("polygon news failed for %s: %s", t, e)
    if s.finnhub_api_key:
        try:
            return _cached(f"fhnews:{t}:{limit}", 300, lambda: _finnhub_news(t, limit, s))
        except httpx.HTTPError as e:
            log.warning("finnhub news failed for %s: %s", t, e)
    return {"ticker": t, "articles": [], "error": "news unavailable", "source": "none"}


def _finnhub_news(t: str, limit: int, s: Settings) -> dict:
    today = date.today()
    r = httpx.get("https://finnhub.io/api/v1/company-news", timeout=8, params={
        "symbol": t, "from": (today - timedelta(days=7)).isoformat(), "to": today.isoformat(),
        "token": s.finnhub_api_key})
    r.raise_for_status()
    arts = [{"title": a.get("headline"), "publisher": a.get("source"),
             "published_utc": datetime.fromtimestamp(a["datetime"], tz=timezone.utc).isoformat(),
             "description": (a.get("summary") or "")[:400], "url": a.get("url")}
            for a in r.json()[:limit] if a.get("datetime")]
    return {"ticker": t, "articles": arts, "source": "finnhub"}


# ---------------------------------------------------------------------------
# User store (watchlist + SnapTrade credentials)
# ---------------------------------------------------------------------------
class UserStore(Protocol):
    def get_user(self, email: str) -> dict: ...
    def set_watchlist(self, email: str, tickers: list[str]) -> list[str]: ...


class DemoUserStore:
    """Local, in-memory user store (no Firestore). Seeded from data/local_user.json when present,
    so you can test with your own holdings locally:
        {"watchlist": ["NVDA"], "manual_holdings": [{"symbol": "NVDA", "quantity": 10, "avgCost": 120}],
         "manual_cash": 1000}"""

    def __init__(self):
        self._users: dict[str, dict] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _seed() -> dict:
        local = SERVICE_DIR / "data" / "local_user.json"
        if local.exists():
            return json.loads(local.read_text())
        return {"watchlist": list(demo_data()["watchlist"])} if get_settings().allow_demo_data else {"watchlist": []}

    def get_user(self, email: str) -> dict:
        with self._lock:
            if email not in self._users:
                self._users[email] = {"email": email, **self._seed()}
            return self._users[email]

    def set_watchlist(self, email: str, tickers: list[str]) -> list[str]:
        user = self.get_user(email)
        with self._lock:
            user["watchlist"] = tickers
        return tickers


class FirestoreUserStore:
    """Reads/writes the same `users/{email}` docs as the Flask server."""

    def __init__(self, s: Settings):
        from google.cloud import firestore

        creds = None
        if s.firebase_service_account:
            from google.oauth2 import service_account

            creds = service_account.Credentials.from_service_account_info(json.loads(s.firebase_service_account))
        self.db = firestore.Client(credentials=creds, project=s.project_id, database=s.firestore_database)

    @staticmethod
    def _key(email: str) -> str:
        return email.strip().lower()  # the Flask API keys user docs by lowercase email

    def get_user(self, email: str) -> dict:
        doc = self.db.collection("users").document(self._key(email)).get().to_dict() or {"email": email}
        # The app keeps the watchlist at onboarding.watchlist; expose it at the top level for the tools.
        doc["watchlist"] = (doc.get("onboarding") or {}).get("watchlist") or []
        return doc

    def set_watchlist(self, email: str, tickers: list[str]) -> list[str]:
        # merge=True deep-merges maps, so other onboarding answers are preserved.
        self.db.collection("users").document(self._key(email)).set({"onboarding": {"watchlist": tickers}}, merge=True)
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
# Mirrors DEMO_POSITIONS in server/app.py (simulated SnapTrade account; prices are live)
DEMO_BROKER_POSITIONS = [{"symbol": "AAPL", "quantity": 15, "avgCost": 172.40},
                         {"symbol": "MSFT", "quantity": 8, "avgCost": 401.25},
                         {"symbol": "GOOGL", "quantity": 12, "avgCost": 141.80},
                         {"symbol": "AMZN", "quantity": 10, "avgCost": 178.30},
                         {"symbol": "VTI", "quantity": 20, "avgCost": 246.10}]
DEMO_BROKER_CASH = 1250.0


def get_portfolio(email: str, settings: Settings | None = None) -> dict:
    s = settings or get_settings()
    user = get_user_store().get_user(email)
    holdings = None
    if user.get("snaptrade_user_id") and user.get("snaptrade_user_secret"):
        holdings = _snaptrade_positions(user["snaptrade_user_id"], user["snaptrade_user_secret"])
    demo = user.get("demo_brokerage")
    if holdings is None and (user.get("manual_holdings") or demo):
        # Self-reported positions entered on the Portfolio page (same Firestore field the Flask API writes).
        rows = [{"symbol": h["symbol"], "name": h["symbol"], "quantity": h["quantity"],
                 "avgCost": h.get("avgCost"), "account": "manual"} for h in user.get("manual_holdings") or []]
        cash = float(user.get("manual_cash") or 0)
        if demo:
            label = f"{demo.get('institution', 'Brokerage')} (simulated demo account)"
            rows += [{**h, "name": h["symbol"], "account": label} for h in DEMO_BROKER_POSITIONS]
            cash += DEMO_BROKER_CASH
        holdings = {"source": "manual", "totals": {"totalBalance": cash}, "positions": rows}
    if holdings is None:
        if not s.allow_demo_data:
            return {"source": "none", "positions": [], "total_invested": 0,
                    "note": "No brokerage account is connected. Connect one on the Portfolio page.",
                    "watchlist": user.get("watchlist", [])}
        holdings = demo_data()["portfolio"]

    positions = []
    total = 0.0
    for p in holdings["positions"]:
        q = get_quote(p["symbol"], s)
        price = p.get("price") or q.get("price") or p.get("avgCost") or 0
        mv = p.get("marketValue") or price * float(p.get("quantity") or 0)
        total += mv
        pos = {"symbol": p["symbol"], "name": p.get("name"), "quantity": p.get("quantity"),
               "price": price, "market_value": round(mv, 2), "day_change_pct": q.get("change_pct")}
        if p.get("account"):
            pos["account"] = p["account"]
        if p.get("avgCost"):
            pos["unrealized_pl_pct"] = round(100 * (price - p["avgCost"]) / p["avgCost"], 2)
        positions.append(pos)
    cash = float(holdings.get("totals", {}).get("totalBalance") or 0)
    grand = total + cash
    for pos in positions:
        pos["weight_of_invested_pct"] = round(100 * pos["market_value"] / total, 2) if total else 0
        pos["weight_of_total_pct"] = round(100 * pos["market_value"] / grand, 2) if grand else 0
    positions.sort(key=lambda x: x["market_value"], reverse=True)
    return {
        "source": holdings.get("source", "snaptrade"),
        "total_value": round(grand, 2),
        "total_invested": round(total, 2),
        "cash": cash,
        "cash_pct": round(100 * cash / grand, 2) if grand else 0,
        "positions": positions,
        "largest_position_pct_of_total": positions[0]["weight_of_total_pct"] if positions else 0,
        "watchlist": user.get("watchlist", []),
        **({"note": "Positions in the simulated account are demo share counts priced at live market prices."}
           if demo else {}),
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
