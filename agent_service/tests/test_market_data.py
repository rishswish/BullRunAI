from datetime import date, timedelta

import httpx
import pytest

from bullrun_agent import data_sources as ds
from bullrun_agent.config import Settings


@pytest.fixture(autouse=True)
def clear_cache():
    ds._cache.clear()
    yield
    ds._cache.clear()


def live(**kw) -> Settings:
    return Settings(polygon_api_key="test-key", allow_demo_data=False, **kw)


def fake_polygon(calls: list, sessions: dict[date, dict]):
    def _get(path, params, s):
        calls.append(path)
        day = date.fromisoformat(path.rsplit("/", 1)[1])
        return {"results": [{"T": t, **bar} for t, bar in sessions.get(day, {}).items()]}
    return _get


def test_quote_uses_two_grouped_calls_for_any_number_of_tickers(monkeypatch):
    today = date.today()
    d1, d2 = today - timedelta(days=1), today - timedelta(days=2)
    sessions = {
        d1: {"NVDA": {"o": 100, "h": 106, "l": 99, "c": 105, "v": 10},
             "AAPL": {"o": 200, "h": 201, "l": 195, "c": 196, "v": 5}},
        d2: {"NVDA": {"o": 98, "h": 101, "l": 97, "c": 100, "v": 9},
             "AAPL": {"o": 199, "h": 202, "l": 198, "c": 200, "v": 4}},
    }
    calls: list = []
    monkeypatch.setattr(ds, "_polygon_get", fake_polygon(calls, sessions))
    s = live()
    nvda, aapl = ds.get_quote("nvda", s), ds.get_quote("AAPL", s)
    assert nvda["price"] == 105 and nvda["change_pct"] == 5.0 and nvda["source"] == "polygon"
    assert aapl["change_pct"] == -2.0
    assert str(d1) in nvda["as_of"]
    # today (empty) + d1 + d2, then everything else is served from cache
    assert len(calls) == 3
    ds.get_quote("NVDA", s)
    assert len(calls) == 3


def test_unknown_symbol_is_an_error_not_made_up(monkeypatch):
    d1 = date.today() - timedelta(days=1)
    bar = {"NVDA": {"o": 1, "h": 1, "l": 1, "c": 1}}
    sessions = {d1: bar, d1 - timedelta(days=1): bar}
    monkeypatch.setattr(ds, "_polygon_get", fake_polygon([], sessions))
    out = ds.get_quote("ZZZZ", live())
    assert "error" in out and "price" not in out


def test_rate_limit_is_reported(monkeypatch):
    def boom(path, params, s):
        raise httpx.HTTPStatusError("429", request=httpx.Request("GET", "http://x"),
                                    response=httpx.Response(429))
    monkeypatch.setattr(ds, "_polygon_get", boom)
    assert "rate limit" in ds.get_quote("NVDA", live())["error"]


def test_strict_mode_never_returns_demo_data(monkeypatch):
    s = Settings(polygon_api_key=None, allow_demo_data=False)
    q = ds.get_quote("NVDA", s)
    n = ds.get_news("NVDA", 3, s)
    assert q["source"] == "none" and "price" not in q
    assert n["articles"] == [] and n["source"] == "none"


def test_strict_mode_portfolio_without_broker_is_empty(monkeypatch):
    monkeypatch.setattr(ds, "get_settings", lambda: Settings(allow_demo_data=False))
    ds.get_user_store.cache_clear()
    out = ds.get_portfolio("nobody@example.com", Settings(allow_demo_data=False))
    assert out["positions"] == [] and out["source"] == "none" and "brokerage" in out["note"]
    ds.get_user_store.cache_clear()
