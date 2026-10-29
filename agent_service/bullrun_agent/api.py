"""FastAPI service that streams the Spade agent over Server-Sent Events.

    POST /api/agent/chat     {message, thread_id?}         -> SSE stream
    POST /api/agent/resume   {thread_id, approved}          -> SSE stream (after an approval request)
    GET  /api/agent/threads/{thread_id}                     -> message history
    GET  /health

SSE event types: route, token, tool_start, tool_end, approval_required, final, error.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import uuid
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langgraph.types import Command
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from . import __version__
from .config import get_settings
from .graph import build_graph, make_checkpointer
from .graph.builder import _text_of
from .rag import get_index
from .tools import load_tools

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("bullrun.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    tools = await load_tools(s.tools_mode, s.mcp_server_url)
    checkpointer, cm = await make_checkpointer(s)
    app.state.graph = build_graph(tools, checkpointer, s)
    get_index()  # warm the RAG index so the first question isn't slow
    log.info("agent ready: provider=%s model=%s tools=%s mode=%s demo_market=%s demo_portfolio=%s",
             s.llm_provider, s.llm_model, [t.name for t in tools], s.tools_mode, s.demo_market, s.demo_portfolio)
    yield
    if cm is not None:
        await cm.__aexit__(None, None, None)


app = FastAPI(title="BullRun Agent Service", version=__version__, lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=get_settings().cors_origins.split(","),
                   allow_methods=["*"], allow_headers=["*"])


# ---------------------------------------------------------------------------
# Auth + rate limit
# ---------------------------------------------------------------------------
class User(BaseModel):
    email: str
    name: str | None = None


def current_user(authorization: str | None = Header(default=None)) -> User:
    s = get_settings()
    if s.auth_disabled:
        return User(email="demo@bullrun.ai", name="Demo Investor")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing bearer token")
    from google.auth.transport import requests as g_requests
    from google.oauth2 import id_token

    try:
        info = id_token.verify_oauth2_token(authorization.split(" ", 1)[1], g_requests.Request(),
                                            s.google_client_id, clock_skew_in_seconds=10)
    except Exception as e:
        raise HTTPException(401, "Invalid token") from e
    return User(email=info["email"], name=info.get("name"))


_hits: dict[str, deque] = defaultdict(deque)
RATE_LIMIT, RATE_WINDOW = 20, 60.0  # requests per user per minute (LLM cost guard)


def rate_limited_user(user: User = Depends(current_user)) -> User:
    now, q = time.time(), _hits[user.email]
    while q and now - q[0] > RATE_WINDOW:
        q.popleft()
    if len(q) >= RATE_LIMIT:
        raise HTTPException(429, "Too many requests, slow down a little")
    q.append(now)
    return user


# ---------------------------------------------------------------------------
# Streaming
# ---------------------------------------------------------------------------
class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    thread_id: str | None = None


class ResumeIn(BaseModel):
    thread_id: str
    approved: bool


class FeedbackIn(BaseModel):
    run_id: str
    score: int = Field(ge=0, le=1)
    comment: str | None = Field(default=None, max_length=1000)


def _user_hash(email: str) -> str:
    return hashlib.sha256(email.lower().encode()).hexdigest()[:12]


_recent_runs: dict[str, deque] = defaultdict(lambda: deque(maxlen=200))  # user -> run ids they own


def _config(user: User, thread_id: str, run_id: str | None = None) -> dict:
    # Threads are namespaced by user so one user can never load another's memory.
    cfg = {"configurable": {"thread_id": f"{user.email}:{thread_id}", "user_email": user.email,
                            "user_name": user.name},
           "metadata": {"user_id": _user_hash(user.email), "thread_id": thread_id},
           "tags": ["bullrun-chat"], "run_name": "spade-chat"}
    if run_id:
        cfg["run_id"] = uuid.UUID(run_id)  # becomes the LangSmith trace id
        _recent_runs[user.email].append(run_id)
    return cfg


def _sse(event: str, data: Any) -> dict:
    return {"event": event, "data": json.dumps(data, default=str)}


def _summarize_tool(msg: ToolMessage) -> tuple[str, list[dict]]:
    """Short human-readable summary of a tool result + any filing citations."""
    raw = _text_of(msg.content)
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return raw[:160], []
    if not isinstance(data, dict):
        return raw[:160], []
    if data.get("error"):
        return f"error: {data['error']}", []
    if msg.name == "get_quote":
        pct = data.get("change_pct")
        return (f"{data.get('ticker')} ${data.get('price')} ({pct:+}%)" if pct is not None else data.get("ticker")), []
    if msg.name == "get_news":
        return f"{len(data.get('articles', []))} articles for {data.get('ticker')}", []
    if msg.name == "get_portfolio":
        return f"{len(data.get('positions', []))} positions, ${data.get('total_invested'):,} invested", []
    if msg.name == "search_filings":
        res = data.get("results", [])
        cites = [{"id": r["source_id"], **r["citation"]} for r in res]
        return f"{len(res)} filing passages", cites
    if msg.name == "update_watchlist":
        return data.get("status", "done"), []
    return raw[:160], []


async def _stream(graph, payload, config: dict, thread_id: str) -> AsyncIterator[dict]:
    run_id = str(config.get("run_id", ""))
    started = time.perf_counter()
    usage = {"input_tokens": 0, "output_tokens": 0}
    citations: list[dict] = []
    tools_used: list[str] = []
    interrupted = False
    yield _sse("thread", {"thread_id": thread_id, "run_id": run_id})
    try:
        async for mode, chunk in graph.astream(payload, config, stream_mode=["messages", "updates"]):
            if mode == "messages":
                msg, meta = chunk
                if meta.get("langgraph_node") == "agent" and isinstance(msg, AIMessageChunk):
                    text = _text_of(msg.content)
                    if text:
                        yield _sse("token", {"text": text})
                continue
            # mode == "updates": {node_name: state_delta}
            for node, delta in chunk.items():
                if node == "__interrupt__":
                    interrupted = True
                    for intr in delta:
                        yield _sse("approval_required", intr.value)
                elif node == "guardrail":
                    yield _sse("route", {"category": delta.get("category"),
                                         "personal_advice": delta.get("personal_advice")})
                elif node == "agent":
                    for m in delta.get("messages", []):
                        if m.usage_metadata:
                            usage["input_tokens"] += m.usage_metadata.get("input_tokens", 0)
                            usage["output_tokens"] += m.usage_metadata.get("output_tokens", 0)
                        for tc in getattr(m, "tool_calls", None) or []:
                            tools_used.append(tc["name"])
                            yield _sse("tool_start", {"id": tc["id"], "name": tc["name"], "args": tc["args"]})
                elif node == "tools":
                    for m in delta.get("messages", []):
                        summary, cites = _summarize_tool(m)
                        citations.extend(cites)
                        yield _sse("tool_end", {"id": m.tool_call_id, "name": m.name, "summary": summary,
                                                "status": getattr(m, "status", "success")})
        if not interrupted:
            state = await graph.aget_state(config)
            final = state.values["messages"][-1]
            yield _sse("final", {
                "text": _text_of(final.content),
                "category": state.values.get("category"),
                "citations": citations,
                "tools_used": tools_used,
                "usage": usage,
                "latency_ms": round(1000 * (time.perf_counter() - started)),
                "run_id": run_id,
            })
        log.info(json.dumps({"event": "chat", "run_id": run_id, "thread_id": thread_id, "tools": tools_used,
                             **usage, "latency_ms": round(1000 * (time.perf_counter() - started))}))
    except Exception as e:  # surface failures to the UI instead of a dead stream
        log.exception("agent stream failed run_id=%s", run_id)
        yield _sse("error", {"message": "Spade hit an error. Please try again.", "detail": e.__class__.__name__,
                             "run_id": run_id})


@app.post("/api/agent/chat")
async def chat(body: ChatIn, request: Request, user: User = Depends(rate_limited_user)):
    thread_id = body.thread_id or uuid.uuid4().hex
    graph = request.app.state.graph
    if (await graph.aget_state(_config(user, thread_id))).next:
        # a pending approval exists: a new message implicitly declines it
        await graph.ainvoke(Command(resume={"approved": False}), _config(user, thread_id))
    run_id = str(uuid.uuid4())
    payload = {"messages": [HumanMessage(body.message)]}
    return EventSourceResponse(_stream(graph, payload, _config(user, thread_id, run_id), thread_id),
                               headers={"X-Run-ID": run_id})


@app.post("/api/agent/resume")
async def resume(body: ResumeIn, request: Request, user: User = Depends(rate_limited_user)):
    graph = request.app.state.graph
    if not (await graph.aget_state(_config(user, body.thread_id))).next:
        raise HTTPException(409, "Nothing is waiting for approval on this thread")
    run_id = str(uuid.uuid4())
    cfg = _config(user, body.thread_id, run_id)
    return EventSourceResponse(_stream(graph, Command(resume={"approved": body.approved}), cfg, body.thread_id),
                               headers={"X-Run-ID": run_id})


@app.post("/api/agent/feedback")
async def feedback(body: FeedbackIn, user: User = Depends(current_user)):
    if body.run_id not in _recent_runs[user.email]:
        raise HTTPException(404, "Unknown run")
    record = {"event": "feedback", "run_id": body.run_id, "score": body.score, "user_id": _user_hash(user.email)}
    if os.environ.get("LANGSMITH_API_KEY") and os.environ.get("LANGSMITH_TRACING", "").lower() == "true":
        from langsmith import Client

        try:
            Client().create_feedback(run_id=body.run_id, key="user_score", score=body.score, comment=body.comment)
            record["langsmith"] = True
        except Exception as e:  # feedback must never break the chat
            log.warning("langsmith feedback failed: %s", e)
    log.info(json.dumps(record))
    return {"ok": True}


@app.get("/api/agent/threads/{thread_id}")
async def thread_history(thread_id: str, request: Request, user: User = Depends(current_user)):
    state = await request.app.state.graph.aget_state(_config(user, thread_id))
    msgs = []
    for m in state.values.get("messages", []) if state.values else []:
        if isinstance(m, HumanMessage):
            msgs.append({"role": "user", "text": _text_of(m.content)})
        elif isinstance(m, AIMessage) and m.content:
            msgs.append({"role": "assistant", "text": _text_of(m.content)})
    return {"thread_id": thread_id, "messages": msgs, "pending_approval": bool(state.next)}


@app.get("/health")
async def health():
    s = get_settings()
    idx = get_index()
    return {"status": "ok", "version": __version__, "provider": s.llm_provider, "model": s.llm_model,
            "tools_mode": s.tools_mode, "demo_market": s.demo_market, "demo_portfolio": s.demo_portfolio,
            "filings_index": {"chunks": len(idx.chunks), "tickers": idx.tickers} if idx else None}
