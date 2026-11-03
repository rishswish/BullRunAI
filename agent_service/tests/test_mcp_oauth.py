"""The full Claude-connector flow against a real HTTP server: discovery, dynamic registration,
Google sign-in (stubbed), PKCE token exchange, refresh, then account tools as that user."""
import asyncio
import base64
import hashlib
import importlib
import secrets
import socket
import threading
import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import uvicorn

CALLBACK = "https://claude.ai/api/mcp/auth_callback"


@pytest.fixture
def server(monkeypatch):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    monkeypatch.setenv("ALLOW_DEMO_DATA", "true")
    monkeypatch.setenv("SESSION_SECRET", "s" * 32)
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "google-client")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "google-secret")
    monkeypatch.setenv("MCP_PUBLIC_URL", base)

    from bullrun_agent import config, data_sources, mcp_server
    config.get_settings.cache_clear()
    data_sources.get_user_store.cache_clear()
    m = importlib.reload(mcp_server)

    async def signed_in_as(_code):
        return "investor@example.com"
    m.oauth.google_email = signed_in_as

    srv = uvicorn.Server(uvicorn.Config(m.mcp.streamable_http_app(), port=port, log_level="warning"))
    threading.Thread(target=srv.run, daemon=True).start()
    for _ in range(50):
        if srv.started:
            break
        time.sleep(0.1)
    yield base
    srv.should_exit = True
    monkeypatch.undo()
    config.get_settings.cache_clear()
    data_sources.get_user_store.cache_clear()
    importlib.reload(mcp_server)


def _connect(base: str) -> dict:
    with httpx.Client(base_url=base) as h:
        assert h.post("/mcp", json={}).status_code == 401  # no token, no access
        meta = h.get("/.well-known/oauth-authorization-server").json()
        client = h.post(meta["registration_endpoint"], json={
            "redirect_uris": [CALLBACK], "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"], "token_endpoint_auth_method": "client_secret_post"}).json()
        verifier = secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        to_google = h.get("/authorize", params={
            "client_id": client["client_id"], "redirect_uri": CALLBACK, "response_type": "code", "state": "xyz",
            "code_challenge": challenge, "code_challenge_method": "S256"}).headers["location"]
        assert to_google.startswith("https://accounts.google.com/")
        state = parse_qs(urlparse(to_google).query)["state"][0]
        back = urlparse(h.get("/oauth/google/callback", params={"code": "g", "state": state}).headers["location"])
        assert back.geturl().startswith(CALLBACK) and parse_qs(back.query)["state"] == ["xyz"]
        form = {"grant_type": "authorization_code", "code": parse_qs(back.query)["code"][0], "redirect_uri": CALLBACK,
                "client_id": client["client_id"], "client_secret": client["client_secret"]}
        assert h.post("/token", data={**form, "code_verifier": "not-the-verifier"}).status_code == 400
        tokens = h.post("/token", data={**form, "code_verifier": verifier}).json()
        refreshed = h.post("/token", data={"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"],
                                           "client_id": client["client_id"],
                                           "client_secret": client["client_secret"]}).json()
        assert refreshed["access_token"]
        return tokens


async def _call(base: str, token: str, tool: str, args: dict | None = None):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    async with streamablehttp_client(f"{base}/mcp", headers={"Authorization": f"Bearer {token}"}) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            res = await s.call_tool(tool, args or {})
            return res.isError, res.content[0].text


def test_claude_can_sign_in_and_edit_the_users_watchlist(server):
    token = _connect(server)["access_token"]
    err, text = asyncio.run(_call(server, token, "update_watchlist", {"add": ["PLTR"]}))
    assert not err and '"status": "applied"' in text and "PLTR" in text

    from bullrun_agent import data_sources
    user = data_sources.get_user_store().get_user("investor@example.com")
    assert "PLTR" in user["watchlist"]
    assert user["mcp_connection"]["at"]  # the app's "Use in Claude" panel shows this


def test_service_token_gets_public_tools_but_no_account(server):
    from bullrun_agent.mcp_auth import service_token

    token = service_token("s" * 32)
    assert asyncio.run(_call(server, token, "get_quote", {"ticker": "NVDA"}))[0] is False
    err, text = asyncio.run(_call(server, token, "get_watchlist"))
    assert err and "isn't signed in" in text


def test_client_id_metadata_documents_are_accepted(monkeypatch):
    from bullrun_agent import mcp_auth

    provider = mcp_auth.GoogleOAuthProvider(public_url="https://mcp.example", secret="s" * 32,
                                            google_client_id="g", google_client_secret="gs")
    url = "https://claude.ai/oauth/mcp-client-metadata"

    class Resp:
        def __init__(self, body):
            self.body = body

        def raise_for_status(self):
            return self

        def json(self):
            return self.body

    class Http:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, u):
            return Resp({"client_id": u, "client_name": "Claude", "redirect_uris": [CALLBACK]})

    monkeypatch.setattr(mcp_auth.httpx, "AsyncClient", Http)
    client = asyncio.run(provider.get_client(url))
    assert client.client_id == url and str(client.redirect_uris[0]) == CALLBACK

    async def mismatched(self, u):  # a document that claims a different client id is rejected
        return Resp({"client_id": "https://someone-else", "redirect_uris": [CALLBACK]})
    monkeypatch.setattr(Http, "get", mismatched)
    assert asyncio.run(provider.get_client("https://claude.ai/other")) is None


def test_mcp_tool_calls_traced_except_spade(monkeypatch):
    """Claude's tool calls are traced with app + user; Spade's service-token calls are skipped."""
    from types import SimpleNamespace

    from bullrun_agent import mcp_server

    seen = []

    def fake_traceable(**_):
        def deco(fn):
            def run(*a, langsmith_extra=None, **kw):
                seen.append(langsmith_extra)
                return fn(*a, **kw)
            return run
        return deco

    monkeypatch.setattr(mcp_server, "traceable", fake_traceable)
    tool = mcp_server.traced(lambda ticker: {"ticker": ticker})

    monkeypatch.setattr(mcp_server, "get_access_token",
                        lambda: SimpleNamespace(client_id="claude-123", subject="me@x.com"))
    assert tool("NVDA") == {"ticker": "NVDA"}
    assert seen[-1]["metadata"] == {"mcp_client": "claude-123", "user_email": "me@x.com"}
    assert seen[-1]["project_name"] == mcp_server.TRACE_PROJECT

    monkeypatch.setattr(mcp_server, "get_access_token",
                        lambda: SimpleNamespace(client_id="br-agent", subject=""))
    tool("AMD")
    assert len(seen) == 1  # Spade's call not traced again
