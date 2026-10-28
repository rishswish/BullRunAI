"""Provider-agnostic chat model + embeddings factory.

Swap providers with LLM_PROVIDER / LLM_MODEL - the graph, tools and evals never
import a vendor SDK directly. `ScriptedChatModel` is a deterministic fake used by
unit tests and keyless CI so the whole graph can be exercised offline.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Sequence
from typing import Any

import numpy as np
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from .config import Settings, get_settings


# ---------------------------------------------------------------------------
# Chat models
# ---------------------------------------------------------------------------
def get_chat_model(settings: Settings | None = None, *, model: str | None = None,
                   temperature: float | None = None) -> BaseChatModel:
    s = settings or get_settings()
    name = model or s.llm_model
    temp = s.llm_temperature if temperature is None else temperature

    if s.llm_provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(model=name, temperature=temp, google_api_key=s.google_api_key)
    if s.llm_provider == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(model=name, temperature=temp, api_key=s.openai_api_key)
    if s.llm_provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(model=name, temperature=temp, api_key=s.anthropic_api_key)
    return ScriptedChatModel()


def get_router_model(settings: Settings | None = None) -> BaseChatModel:
    s = settings or get_settings()
    return get_chat_model(s, model=s.router_model or s.llm_model, temperature=0)


# ---------------------------------------------------------------------------
# Deterministic fake model (offline tests / keyless CI)
# ---------------------------------------------------------------------------
_TICKER_RE = re.compile(r"\b[A-Z]{2,5}\b")
_STOP = {"I", "A", "AI", "ETF", "CEO", "USD", "SEC", "EPS", "THE", "AND", "IPO", "OK", "MY", "ME"}


def _tickers(text: str) -> list[str]:
    return [t for t in _TICKER_RE.findall(text) if t not in _STOP]


class ScriptedChatModel(BaseChatModel):
    """Rule-based stand-in for an LLM.

    * With structured-output requests (router) it classifies by keywords.
    * With tools bound it emits plausible tool calls on the first turn and a
      summary of tool results on the second turn.
    """

    tool_names: list[str] = []
    structured_schema: Any = None

    @property
    def _llm_type(self) -> str:
        return "scripted-fake"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> ScriptedChatModel:
        names = [getattr(t, "name", None) or t.get("name") for t in tools]
        return self.model_copy(update={"tool_names": names})

    def with_structured_output(self, schema: Any, **kwargs: Any):  # type: ignore[override]
        model = self

        class _Structured:
            def invoke(self, messages, config=None):
                text = _last_human(messages)
                return schema(**model._route(text))

            async def ainvoke(self, messages, config=None):
                return self.invoke(messages, config)

        return _Structured()

    # -- routing heuristics ---------------------------------------------------
    @staticmethod
    def _route(text: str) -> dict:
        t = text.lower()
        finance = any(w in t for w in [
            "stock", "price", "market", "portfolio", "risk", "revenue", "earn", "filing", "10-k",
            "watchlist", "share", "invest", "news", "nvda", "aapl", "msft", "tsla", "fed", "etf",
            "dividend", "valuation", "holding", "sector", "trade", "bond",
        ]) or bool(_tickers(text))
        injection = any(w in t for w in ["ignore previous", "ignore all", "system prompt", "jailbreak"])
        if injection:
            return {"category": "unsafe", "reason": "prompt injection attempt", "personal_advice": False}
        if not finance:
            return {"category": "off_topic", "reason": "not about markets or investing", "personal_advice": False}
        advice = any(w in t for w in ["should i buy", "should i sell", "should i invest", "all in", "what should i"])
        return {"category": "finance", "reason": "market question", "personal_advice": advice}

    def _plan_tools(self, text: str) -> list[dict]:
        t = text.lower()
        calls: list[dict] = []
        tickers = _tickers(text) or []
        want = set(self.tool_names)

        def add(name: str, args: dict):
            if name in want:
                calls.append({"name": name, "args": args, "id": f"call_{len(calls)}_{name}", "type": "tool_call"})

        if "add" in t and "watchlist" in t and tickers:
            add("update_watchlist", {"add": tickers[:3], "remove": []})
            return calls
        if any(w in t for w in ["portfolio", "my holdings", "my positions", "exposure"]):
            add("get_portfolio", {})
        if any(w in t for w in ["risk", "10-k", "filing", "annual report", "mention", "disclose", "supply"]):
            add("search_filings", {"query": text, "ticker": tickers[0] if tickers else None})
        if "news" in t or "why" in t:
            for tk in tickers[:2]:
                add("get_news", {"ticker": tk, "limit": 3})
        if any(w in t for w in ["price", "quote", "trading", "how is", "doing", "compare"]) or (tickers and not calls):
            for tk in tickers[:3]:
                add("get_quote", {"ticker": tk})
        return calls

    def _generate(self, messages: list[BaseMessage], stop: list[str] | None = None,
                  run_manager: CallbackManagerForLLMRun | None = None, **kwargs: Any) -> ChatResult:
        last = messages[-1]
        if isinstance(last, ToolMessage):
            # Summarise every tool result since the last human turn.
            results = []
            for m in reversed(messages):
                if isinstance(m, HumanMessage):
                    break
                if isinstance(m, ToolMessage):
                    results.append(f"- {m.name}: {str(m.content)[:220]}")
            text = "Here is what I found:\n" + "\n".join(reversed(results))
            msg = AIMessage(content=text)
        else:
            calls = self._plan_tools(_last_human(messages)) if self.tool_names else []
            msg = AIMessage(content="" if calls else "I can help with markets, filings and your portfolio.",
                            tool_calls=calls)
        msg.usage_metadata = {"input_tokens": 50, "output_tokens": 30, "total_tokens": 80}
        return ChatResult(generations=[ChatGeneration(message=msg)])


def _last_human(messages: Sequence[Any]) -> str:
    for m in reversed(list(messages)):
        if isinstance(m, HumanMessage):
            return str(m.content)
        if isinstance(m, tuple) and m[0] in ("user", "human"):
            return m[1]
        if isinstance(m, dict) and m.get("role") in ("user", "human"):
            return m.get("content", "")
    return ""


# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------
class HashEmbeddings:
    """Dependency-free hashed bag-of-words embeddings (offline tests only)."""

    def __init__(self, dim: int = 384):
        self.dim = dim

    def _embed(self, text: str) -> list[float]:
        v = np.zeros(self.dim, dtype=np.float32)
        for tok in re.findall(r"[a-z0-9]+", text.lower()):
            h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
            v[h % self.dim] += 1.0
        n = np.linalg.norm(v)
        return (v / n if n else v).tolist()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


def get_embeddings(settings: Settings | None = None):
    s = settings or get_settings()
    if s.embedding_provider == "gemini":
        from langchain_google_genai import GoogleGenerativeAIEmbeddings

        return GoogleGenerativeAIEmbeddings(model=s.embedding_model, google_api_key=s.google_api_key)
    if s.embedding_provider == "openai":
        from langchain_openai import OpenAIEmbeddings

        return OpenAIEmbeddings(model=s.embedding_model, api_key=s.openai_api_key)
    return HashEmbeddings()


def parse_json_loose(text: str) -> dict:
    """Pull the first JSON object out of an LLM reply (tolerates ```json fences)."""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError(f"No JSON object in: {text[:200]}")
    return json.loads(m.group(0))


Factory = Callable[[], BaseChatModel]
