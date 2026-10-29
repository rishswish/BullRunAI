"""Chat with Spade in the terminal: same graph, tools and memory as the API.

    python -m bullrun_agent.cli                     # interactive chat
    python -m bullrun_agent.cli "Why is NVDA moving?"   # one question

Shows the guardrail decision, each tool call and its result summary, approval
prompts for watchlist edits, then the answer with tokens and latency.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
import uuid

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from .config import get_settings
from .graph import build_graph
from .graph.builder import _text_of
from .rag import get_index
from .tools import load_tools

DIM, BOLD, GREEN, YELLOW, RESET = "\033[2m", "\033[1m", "\033[32m", "\033[33m", "\033[0m"


async def run_turn(graph, payload, cfg) -> None:
    cfg = {**cfg, "run_id": uuid.uuid4()}  # same id as the LangSmith trace
    start = time.perf_counter()
    tokens = 0
    async for chunk in graph.astream(payload, cfg, stream_mode="updates"):
        for node, delta in chunk.items():
            if node == "guardrail":
                print(f"{DIM}  route: {delta.get('category')}"
                      f"{' (advice-seeking)' if delta.get('personal_advice') else ''}{RESET}")
            elif node == "agent":
                for m in delta.get("messages", []):
                    tokens += (m.usage_metadata or {}).get("total_tokens", 0)
                    for tc in getattr(m, "tool_calls", None) or []:
                        print(f"{DIM}  → {tc['name']}({json.dumps(tc['args'])[:120]}){RESET}")
            elif node == "tools":
                for m in delta.get("messages", []):
                    if isinstance(m, ToolMessage):
                        print(f"{DIM}  ← {m.name}: {_text_of(m.content)[:140]}{RESET}")
            elif node == "__interrupt__":
                for intr in delta:
                    v = intr.value
                    ans = input(f"{YELLOW}  Approve watchlist change? add={v.get('add')} "
                                f"remove={v.get('remove')} [y/N] {RESET}").strip().lower()
                    await run_turn(graph, Command(resume={"approved": ans == "y"}), cfg)
                    return
    state = await graph.aget_state(cfg)
    last = state.values["messages"][-1]
    if isinstance(last, AIMessage):
        print(f"\n{GREEN}{BOLD}Spade:{RESET} {_text_of(last.content)}")
    print(f"{DIM}  ({tokens} tokens, {time.perf_counter() - start:.1f}s, trace {cfg['run_id']}){RESET}\n")


async def main() -> None:
    s = get_settings()
    tools = await load_tools(s.tools_mode, s.mcp_server_url)
    graph = build_graph(tools, InMemorySaver(), s)
    idx = get_index()
    if s.finnhub_api_key:
        market = "finnhub (real-time)"
    elif s.polygon_api_key:
        market = "polygon (end-of-day)"
    else:
        market = "demo" if s.allow_demo_data else "NOT CONFIGURED"
    filings = ", ".join(idx.tickers) if idx else "not indexed yet"
    print(f"{BOLD}Spade{RESET} · {s.llm_provider}/{s.llm_model} · market data: {market} · filings: {filings}")
    cfg = {"configurable": {"thread_id": uuid.uuid4().hex, "user_email": "cli@bullrun.ai", "user_name": "you"}}

    if len(sys.argv) > 1:
        await run_turn(graph, {"messages": [HumanMessage(" ".join(sys.argv[1:]))]}, cfg)
        return
    print("Ask anything (Ctrl+C or 'exit' to quit).\n")
    while True:
        try:
            q = input(f"{BOLD}you:{RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if q.lower() in {"exit", "quit"}:
            break
        if q:
            await run_turn(graph, {"messages": [HumanMessage(q)]}, cfg)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
