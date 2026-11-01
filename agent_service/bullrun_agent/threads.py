"""Durable chat history per user, so conversations survive restarts and can be reopened.

The LangGraph checkpointer holds the full working state (tool calls, pending approvals)
for threads that are live in this process. Cloud Run scales to zero, so that memory is
lost when the instance stops. This store keeps the user-visible transcript of every
thread in Firestore (users/{email}/chat_threads/{id}); when a thread isn't in the
checkpointer any more, its transcript is replayed as the conversation history.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from functools import lru_cache
from typing import Protocol

from .config import get_settings

MAX_MESSAGES = 60  # per thread; older turns are trimmed (the agent only sees a token window anyway)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _title(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= 60 else text[:57].rstrip() + "..."


def unique_title(title: str, taken: set[str]) -> str:
    """'NVDA earnings' -> 'NVDA earnings (2)' if the user already has a chat called that."""
    if title not in taken:
        return title
    n = 2
    while f"{title} ({n})" in taken:
        n += 1
    return f"{title} ({n})"


class ThreadStore(Protocol):
    def list(self, email: str) -> list[dict]: ...
    def get(self, email: str, thread_id: str) -> dict | None: ...
    def append(self, email: str, thread_id: str, messages: list[dict]) -> None: ...
    def delete(self, email: str, thread_id: str) -> None: ...
    def set_title(self, email: str, thread_id: str, title: str) -> None: ...


class MemoryThreadStore:
    def __init__(self):
        self._data: dict[str, dict[str, dict]] = {}
        self._lock = threading.Lock()

    def list(self, email: str) -> list[dict]:
        threads = self._data.get(email, {})
        rows = [{"id": k, "title": v["title"], "updated_at": v["updated_at"]} for k, v in threads.items()]
        return sorted(rows, key=lambda r: r["updated_at"], reverse=True)

    def get(self, email: str, thread_id: str) -> dict | None:
        return self._data.get(email, {}).get(thread_id)

    def append(self, email: str, thread_id: str, messages: list[dict]) -> None:
        taken = {r["title"] for r in self.list(email)}
        with self._lock:
            t = self._data.setdefault(email, {}).setdefault(
                thread_id, {"title": unique_title(_title(messages[0]["text"]), taken), "created_at": _now(),
                            "messages": []})
            t["messages"] = (t["messages"] + messages)[-MAX_MESSAGES:]
            t["updated_at"] = _now()

    def delete(self, email: str, thread_id: str) -> None:
        with self._lock:
            self._data.get(email, {}).pop(thread_id, None)

    def set_title(self, email: str, thread_id: str, title: str) -> None:
        with self._lock:
            if t := self._data.get(email, {}).get(thread_id):
                t["title"], t["titled"] = title, True


class FirestoreThreadStore:
    def __init__(self, db):
        self.db = db

    def _col(self, email: str):
        return self.db.collection("users").document(email.strip().lower()).collection("chat_threads")

    def list(self, email: str) -> list[dict]:
        docs = self._col(email).order_by("updated_at", direction="DESCENDING").limit(50).stream()
        return [{"id": d.id, "title": (d.to_dict() or {}).get("title", "Chat"),
                 "updated_at": (d.to_dict() or {}).get("updated_at")} for d in docs]

    def get(self, email: str, thread_id: str) -> dict | None:
        snap = self._col(email).document(thread_id).get()
        return snap.to_dict() if snap.exists else None

    def append(self, email: str, thread_id: str, messages: list[dict]) -> None:
        ref = self._col(email).document(thread_id)
        snap = ref.get()
        if snap.exists:
            doc = snap.to_dict()
        else:
            taken = {r["title"] for r in self.list(email)}
            doc = {"title": unique_title(_title(messages[0]["text"]), taken), "created_at": _now(), "messages": []}
        doc["messages"] = (doc.get("messages", []) + messages)[-MAX_MESSAGES:]
        doc["updated_at"] = _now()
        ref.set(doc)

    def delete(self, email: str, thread_id: str) -> None:
        self._col(email).document(thread_id).delete()

    def set_title(self, email: str, thread_id: str, title: str) -> None:
        self._col(email).document(thread_id).set({"title": title, "titled": True}, merge=True)


@lru_cache
def get_thread_store() -> ThreadStore:
    from . import data_sources as ds

    store = ds.get_user_store()
    if get_settings().demo_portfolio or not hasattr(store, "db"):
        return MemoryThreadStore()
    return FirestoreThreadStore(store.db)
