"""'I bought 10 more NVDA': the trade is checked, shown for approval, and only then saved."""
import json

import pytest
from langchain_core.messages import ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from bullrun_agent import data_sources as ds
from bullrun_agent.graph import build_graph
from bullrun_agent.tools import load_tools, plan_holdings_change


@pytest.fixture
def user(monkeypatch):
    email = "trader@bullrun.ai"
    u = ds.get_user_store().get_user(email)
    u.pop("snaptrade_user_id", None)
    u["manual_holdings"] = [{"symbol": "NVDA", "quantity": 10, "avgCost": 100.0}]
    monkeypatch.setattr(ds, "get_quote", lambda t, *a: {"ticker": t, "price": 200.0, "source": "finnhub"})
    return email


def test_buy_more_averages_the_cost(user):
    plan = plan_holdings_change(user, [{"symbol": "nvda", "shares": 10, "price": 150}])
    assert plan["changes"][0]["after"] == {"quantity": 20, "avgCost": 125.0}
    assert plan["changes"][0]["before"]["quantity"] == 10


def test_no_price_uses_current_price_and_new_stock_is_added(user):
    plan = plan_holdings_change(user, [{"symbol": "TSLA", "shares": 5}])
    c = plan["changes"][0]
    assert c["price"] == 200.0 and c["price_source"] == "current price" and c["before"] is None
    assert {"symbol": "TSLA", "quantity": 5, "avgCost": 200.0} in plan["holdings"]


def test_selling_keeps_cost_and_selling_everything_removes_it(user):
    assert plan_holdings_change(user, [{"symbol": "NVDA", "shares": -4}])["changes"][0]["after"] == \
        {"quantity": 6, "avgCost": 100.0}
    plan = plan_holdings_change(user, [{"symbol": "NVDA", "shares": -10}])
    assert plan["changes"][0]["after"] is None and plan["holdings"] == []


def test_cannot_sell_more_than_held_or_edit_a_brokerage(user):
    assert "can't sell" in plan_holdings_change(user, [{"symbol": "NVDA", "shares": -11}])["error"]
    assert "can't sell" in plan_holdings_change(user, [{"symbol": "AMD", "shares": -1}])["error"]
    ds.get_user_store().get_user(user)["snaptrade_user_id"] = "x"
    assert "brokerage" in plan_holdings_change(user, [{"symbol": "NVDA", "shares": 1}])["error"]


async def test_trade_waits_for_approval_then_saves(user):
    g = build_graph(await load_tools(), InMemorySaver())
    cfg = {"configurable": {"thread_id": "buy", "user_email": user}}
    out = await g.ainvoke({"messages": [("user", "I bought 10 more NVDA")]}, cfg)
    card = out["__interrupt__"][0].value
    assert card["type"] == "approve_holdings" and card["changes"][0]["after"]["quantity"] == 20
    assert ds.get_user_store().get_user(user)["manual_holdings"][0]["quantity"] == 10  # nothing saved yet

    out = await g.ainvoke(Command(resume={"approved": True}), cfg)
    result = json.loads(next(m for m in out["messages"] if isinstance(m, ToolMessage)).content)
    assert result["status"] == "applied"
    saved = ds.get_user_store().get_user(user)["manual_holdings"][0]
    assert saved == {"symbol": "NVDA", "quantity": 20, "avgCost": 150.0}


async def test_declined_trade_changes_nothing(user):
    g = build_graph(await load_tools(), InMemorySaver())
    cfg = {"configurable": {"thread_id": "nope", "user_email": user}}
    await g.ainvoke({"messages": [("user", "I sold 3 NVDA")]}, cfg)
    await g.ainvoke(Command(resume={"approved": False}), cfg)
    assert ds.get_user_store().get_user(user)["manual_holdings"][0]["quantity"] == 10
