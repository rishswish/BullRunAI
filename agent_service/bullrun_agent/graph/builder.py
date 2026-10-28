"""The Spade research agent as a LangGraph state machine.

    START -> guardrail --finance--> agent <-> tools
                 |                    |
                 +--off_topic/unsafe--+--> respond_refusal -> END
                                      +--> compliance -> END

* guardrail   - structured-output classifier (replaces the old keyword regex);
                cheap model, temperature 0.
* agent       - tool-calling LLM over a trimmed window of the thread's history.
* tools       - ToolNode, executes parallel tool calls, turns exceptions into
                ToolMessages the model can recover from. `update_watchlist`
                pauses the whole graph with interrupt() for user approval.
* compliance  - deterministic post-processing: disclaimer on advice-seeking
                turns, guaranteed even if the model forgets.

State is checkpointed per thread_id (InMemorySaver locally, Postgres in prod),
which gives multi-turn memory and makes interrupt/resume possible.
"""
from __future__ import annotations

from datetime import date
from typing import Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, trim_messages
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode
from pydantic import BaseModel, Field

from ..config import Settings, get_settings
from ..llm import get_chat_model, get_router_model
from . import prompts


class AgentState(MessagesState):
    category: str
    personal_advice: bool
    steps: int


class RouteDecision(BaseModel):
    """Guardrail classification of the latest user message."""

    category: Literal["finance", "off_topic", "unsafe"] = Field(description="Topic class")
    personal_advice: bool = Field(description="User asks what they personally should buy/sell/allocate")
    reason: str = Field(description="One short phrase explaining the decision")


def build_graph(tools: list[BaseTool], checkpointer=None, settings: Settings | None = None,
                chat_model=None, router_model=None):
    s = settings or get_settings()
    llm = (chat_model or get_chat_model(s)).bind_tools(tools)
    router = (router_model or get_router_model(s)).with_structured_output(RouteDecision)
    trimmer = trim_messages(max_tokens=s.max_history_messages, token_counter=len, strategy="last",
                            start_on="human", include_system=False, allow_partial=False)

    # -- nodes ---------------------------------------------------------------
    async def guardrail(state: AgentState) -> dict:
        recent = [m for m in state["messages"] if isinstance(m, (HumanMessage, AIMessage)) and m.content][-4:]
        decision: RouteDecision = await router.ainvoke([SystemMessage(prompts.ROUTER_PROMPT), *recent])
        return {"category": decision.category, "personal_advice": decision.personal_advice, "steps": 0}

    async def agent(state: AgentState, config: RunnableConfig) -> dict:
        cfg = config.get("configurable", {})
        system = SystemMessage(prompts.AGENT_PROMPT.format(
            today=date.today().isoformat(), user_name=cfg.get("user_name") or "the user"))
        history = trimmer.invoke(state["messages"])
        steps = state.get("steps", 0) + 1
        model = llm
        if steps > s.max_agent_steps:  # loop guard: force a final answer without more tools
            model = chat_model or get_chat_model(s)
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
    g.add_node("tools", ToolNode(tools, handle_tool_errors=True))
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
