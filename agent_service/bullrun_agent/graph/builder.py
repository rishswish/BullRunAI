"""The Spade research agent as a LangGraph state machine.

    START -> guardrail --finance--> agent <-> tools
                 |                    |
                 +--off_topic/unsafe--+--> respond_refusal -> END
                                      +--> compliance -> END

* guardrail   - structured-output classifier (replaces the old keyword regex);
                cheap model, temperature 0.
* agent       - tool-calling LLM over the thread's history, trimmed to a token budget.
* tools       - ToolNode, executes parallel tool calls, turns exceptions into
                ToolMessages the model can recover from. `update_watchlist` and
                `update_holdings` pause the whole graph with interrupt() for approval.
                Filing passages are numbered across searches (S1-S6, then S7-S12).
* compliance  - deterministic post-processing: disclaimer on advice-seeking
                turns, guaranteed even if the model forgets.

State is checkpointed per thread_id (InMemorySaver locally, Postgres in prod),
which gives multi-turn memory and makes interrupt/resume possible.
"""
from __future__ import annotations

import json
from datetime import date
from typing import Literal

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage, trim_messages
from langchain_core.messages.utils import count_tokens_approximately
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode
from pydantic import BaseModel, Field

from ..config import Settings, get_settings
from ..llm import get_chat_model, get_fallback_settings, get_router_model
from . import prompts


class AgentState(MessagesState):
    category: str
    personal_advice: bool
    steps: int


def trim_history(messages: list[BaseMessage], max_tokens: int) -> list[BaseMessage]:
    """Keep the current turn whole and fill the rest of the token budget with the newest older turns."""
    last_human = next((i for i in range(len(messages) - 1, -1, -1) if isinstance(messages[i], HumanMessage)), 0)
    older, current = messages[:last_human], messages[last_human:]
    budget = max_tokens - count_tokens_approximately(current)
    if budget <= 0 or not older:
        return current
    # start_on="human" so we never open on a tool result whose tool call was cut
    kept = trim_messages(older, max_tokens=budget, token_counter=count_tokens_approximately,
                         strategy="last", start_on="human", include_system=False, allow_partial=False)
    return [*kept, *current]


class RouteDecision(BaseModel):
    """Guardrail classification of the latest user message."""

    category: Literal["finance", "off_topic", "unsafe"] = Field(description="Topic class")
    personal_advice: bool = Field(description="User asks what they personally should buy/sell/allocate")
    reason: str = Field(description="One short phrase explaining the decision")


def _filing_results(m: BaseMessage) -> dict | None:
    if not (isinstance(m, ToolMessage) and m.name == "search_filings"):
        return None
    try:
        data = json.loads(_text_of(m.content))
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) and data.get("results") else None


def number_sources(history: list[BaseMessage], new: list[BaseMessage]) -> list[BaseMessage]:
    """Every search_filings call numbers its passages S1..S6. When one answer needs two searches,
    continue the count (S7..S12) so each [S#] the model writes points at exactly one passage."""
    used = 0
    for m in reversed(history):  # sources already handed out in this turn
        if isinstance(m, HumanMessage):
            break
        if data := _filing_results(m):
            used += len(data["results"])
    out = []
    for m in new:
        data = _filing_results(m)
        if data:
            for r in data["results"]:
                used += 1
                r["source_id"] = f"S{used}"
            m = m.model_copy(update={"content": json.dumps(data, default=str)})
        out.append(m)
    return out


MAX_SEARCHES_PER_COMPANY = 2  # per question; more rarely adds anything, just tokens and wait


def _ticker_of(call: dict) -> str:
    return str((call.get("args") or {}).get("ticker") or "any").upper()


def cap_filing_searches(history: list[BaseMessage], last: AIMessage) -> tuple[list[dict], list[ToolMessage]]:
    """Split the model's tool calls into ones to run and filing searches over the per-company cap.
    The extra searches get a short note back instead of running."""
    done: dict[str, int] = {}
    calls_by_id = {}
    for m in reversed(history[:-1]):  # this turn only
        if isinstance(m, HumanMessage):
            break
        if isinstance(m, AIMessage):
            calls_by_id.update({c["id"]: c for c in m.tool_calls})
    for m in history:
        if isinstance(m, ToolMessage) and m.name == "search_filings" and m.tool_call_id in calls_by_id:
            t = _ticker_of(calls_by_id[m.tool_call_id])
            done[t] = done.get(t, 0) + 1
    run, skipped = [], []
    for c in last.tool_calls:
        if c["name"] == "search_filings":
            t = _ticker_of(c)
            if done.get(t, 0) >= MAX_SEARCHES_PER_COMPANY:
                note = {"status": "skipped",
                        "note": f"Already searched {t} filings {MAX_SEARCHES_PER_COMPANY} times for this "
                                "question. Answer now from the passages you have."}
                skipped.append(ToolMessage(json.dumps(note), tool_call_id=c["id"], name=c["name"]))
                continue
            done[t] = done.get(t, 0) + 1
        run.append(c)
    return run, skipped


def build_graph(tools: list[BaseTool], checkpointer=None, settings: Settings | None = None,
                chat_model=None, router_model=None):
    s = settings or get_settings()
    base = chat_model or get_chat_model(s)
    llm = base.bind_tools(tools)
    router = (router_model or get_router_model(s)).with_structured_output(RouteDecision)
    fb = get_fallback_settings(s) if chat_model is None else None
    if fb:  # e.g. Gemini rate-limited -> same turn retried on OpenAI
        backup = get_chat_model(fb)
        llm = llm.with_fallbacks([backup.bind_tools(tools)])
        router = router.with_fallbacks([get_chat_model(fb, temperature=0).with_structured_output(RouteDecision)])
        base = base.with_fallbacks([backup])

    # -- nodes ---------------------------------------------------------------
    async def guardrail(state: AgentState) -> dict:
        recent = [m for m in state["messages"] if isinstance(m, (HumanMessage, AIMessage)) and m.content][-4:]
        decision: RouteDecision = await router.ainvoke([SystemMessage(prompts.ROUTER_PROMPT), *recent])
        return {"category": decision.category, "personal_advice": decision.personal_advice, "steps": 0}

    async def agent(state: AgentState, config: RunnableConfig) -> dict:
        cfg = config.get("configurable", {})
        system = SystemMessage(prompts.AGENT_PROMPT.format(
            today=date.today().isoformat(), user_name=cfg.get("user_name") or "the user"))
        history = trim_history(state["messages"], s.max_history_tokens)
        steps = state.get("steps", 0) + 1
        model = llm
        if steps > s.max_agent_steps:  # loop guard: force a final answer without more tools
            model = base
            history = [*history, HumanMessage("Tool budget reached. Answer now with what you have.")]
        response = await model.ainvoke([system, *history], config)
        return {"messages": [response], "steps": steps}

    def compliance(state: AgentState) -> dict:
        last = state["messages"][-1]
        if state.get("personal_advice") and isinstance(last, AIMessage) and prompts.DISCLAIMER not in str(last.content):
            text = last.content if isinstance(last.content, str) else _text_of(last.content)
            # Same id -> MessagesState reducer replaces the message instead of appending.
            return {"messages": [AIMessage(content=text + prompts.DISCLAIMER, id=last.id,
                                           usage_metadata=last.usage_metadata)]}
        return {}

    tool_node = ToolNode(tools, handle_tool_errors=True)

    async def run_tools(state: AgentState, config: RunnableConfig) -> dict:
        msgs = state["messages"]
        run, skipped = cap_filing_searches(msgs, msgs[-1])
        ran = []
        if run:
            # ToolNode runs the last message's calls, so hand it a copy holding only the allowed ones
            allowed = msgs[-1].model_copy(update={"tool_calls": run})
            ran = (await tool_node.ainvoke({**state, "messages": [*msgs[:-1], allowed]}, config))["messages"]
        return {"messages": [*number_sources(msgs, ran), *skipped]}

    def respond_refusal(state: AgentState) -> dict:
        text = prompts.REFUSAL_UNSAFE if state["category"] == "unsafe" else prompts.REFUSAL_OFF_TOPIC
        return {"messages": [AIMessage(content=text)]}

    # -- edges ----------------------------------------------------------------
    def after_guardrail(state: AgentState) -> str:
        return "agent" if state["category"] == "finance" else "respond_refusal"

    def after_agent(state: AgentState) -> str:
        last = state["messages"][-1]
        return "tools" if getattr(last, "tool_calls", None) else "compliance"

    g = StateGraph(AgentState)
    g.add_node("guardrail", guardrail)
    g.add_node("agent", agent)
    g.add_node("tools", run_tools)
    g.add_node("compliance", compliance)
    g.add_node("respond_refusal", respond_refusal)
    g.add_edge(START, "guardrail")
    g.add_conditional_edges("guardrail", after_guardrail, ["agent", "respond_refusal"])
    g.add_conditional_edges("agent", after_agent, ["tools", "compliance"])
    g.add_edge("tools", "agent")
    g.add_edge("compliance", END)
    g.add_edge("respond_refusal", END)
    return g.compile(checkpointer=checkpointer)


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    return "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in content)


async def make_checkpointer(settings: Settings | None = None):
    """Postgres when CHECKPOINT_DB_URL is set (durable, multi-instance), else in-memory."""
    s = settings or get_settings()
    if s.checkpoint_db_url:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        cm = AsyncPostgresSaver.from_conn_string(s.checkpoint_db_url)
        saver = await cm.__aenter__()
        await saver.setup()
        return saver, cm
    from langgraph.checkpoint.memory import InMemorySaver

    return InMemorySaver(), None
