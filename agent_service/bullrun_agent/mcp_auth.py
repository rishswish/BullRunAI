"""OAuth for the BullRun MCP server, so Claude (or any MCP client) can act on a user's own data.

Claude's custom connectors speak MCP's OAuth flow: discover the authorization server, register
themselves (dynamic client registration), send the user to /authorize, then swap the code for
tokens with PKCE. Google sign-in can't be that server directly (it has no dynamic client
registration), so this module is a thin authorization server that delegates the login to Google:

    Claude -> /authorize -> Google sign-in -> /oauth/google/callback -> Claude's redirect_uri?code=...
    Claude -> /token (code + PKCE verifier) -> access + refresh token (JWTs naming the user's email)

Codes and tokens are JWTs signed with SESSION_SECRET, so nothing but registered clients needs
storage and a restart doesn't sign anyone out. Registered clients live in Firestore (or memory).
The agent service reaches the same server with a "service" token that carries no user.
"""
from __future__ import annotations

import secrets
import time
from urllib.parse import urlencode

import httpx
import jwt
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    RefreshToken,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import AnyUrl

SCOPE = "bullrun"
ACCESS_TTL = 3600
REFRESH_TTL = 30 * 86400
CODE_TTL = 300
GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"


class MemoryClients:
    def __init__(self):
        self._clients: dict[str, dict] = {}

    def get(self, client_id: str) -> dict | None:
        return self._clients.get(client_id)

    def put(self, client_id: str, data: dict) -> None:
        self._clients[client_id] = data


class FirestoreClients:
    def __init__(self, db):
        self.col = db.collection("mcp_clients")

    def get(self, client_id: str) -> dict | None:
        snap = self.col.document(client_id).get()
        return snap.to_dict() if snap.exists else None

    def put(self, client_id: str, data: dict) -> None:
        self.col.document(client_id).set(data)


def service_token(secret: str, ttl: int = 30 * 86400) -> str:
    """Token the agent service uses to call the MCP server's public tools."""
    now = int(time.time())
    return jwt.encode({"iss": "bullrun-mcp", "typ": "service", "client_id": "br-agent", "iat": now,
                       "exp": now + ttl}, secret, algorithm="HS256")


class GoogleOAuthProvider:
    """OAuthAuthorizationServerProvider for mcp.server.fastmcp, with Google as the identity provider."""

    def __init__(self, *, public_url: str, secret: str, google_client_id: str, google_client_secret: str,
                 clients=None):
        self.public_url = public_url.rstrip("/")
        self.secret = secret
        self.google_client_id = google_client_id
        self.google_client_secret = google_client_secret
        self.clients = clients or MemoryClients()

    @property
    def callback_url(self) -> str:
        return f"{self.public_url}/oauth/google/callback"

    # -- signed tokens ---------------------------------------------------------
    def _sign(self, typ: str, ttl: int, **claims) -> str:
        now = int(time.time())
        return jwt.encode({"iss": "bullrun-mcp", "typ": typ, "iat": now, "exp": now + ttl,
                           "jti": secrets.token_hex(8), **claims}, self.secret, algorithm="HS256")

    def _read(self, token: str, typ: str) -> dict | None:
        try:
            claims = jwt.decode(token, self.secret, algorithms=["HS256"], issuer="bullrun-mcp")
        except jwt.PyJWTError:
            return None
        return claims if claims.get("typ") == typ else None

    # -- clients (dynamic registration) ----------------------------------------
    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        data = self.clients.get(client_id)
        return OAuthClientInformationFull.model_validate(data) if data else None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        self.clients.put(client_info.client_id, client_info.model_dump(mode="json", exclude_none=True))

    # -- authorization: hand the user to Google, carry Claude's request in `state` --------
    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        state = self._sign("state", 900, client_id=client.client_id, redirect_uri=str(params.redirect_uri),
                           explicit=params.redirect_uri_provided_explicitly, challenge=params.code_challenge,
                           scopes=params.scopes or [SCOPE], resource=params.resource, client_state=params.state)
        return GOOGLE_AUTH + "?" + urlencode({
            "client_id": self.google_client_id, "redirect_uri": self.callback_url, "response_type": "code",
            "scope": "openid email profile", "state": state, "prompt": "select_account"})

    async def google_email(self, google_code: str) -> str:
        """Swap Google's code for an ID token and return the verified email."""
        from google.auth.transport import requests as g_requests
        from google.oauth2 import id_token

        async with httpx.AsyncClient(timeout=10) as http:
            r = await http.post(GOOGLE_TOKEN, data={
                "code": google_code, "client_id": self.google_client_id, "client_secret": self.google_client_secret,
                "redirect_uri": self.callback_url, "grant_type": "authorization_code"})
        r.raise_for_status()
        info = id_token.verify_oauth2_token(r.json()["id_token"], g_requests.Request(), self.google_client_id,
                                            clock_skew_in_seconds=10)
        if not info.get("email_verified", True):
            raise ValueError("Google account email is not verified")
        return info["email"].lower()

    def finish_authorization(self, state: str, email: str) -> str:
        """After Google sign-in: mint our code and return Claude's redirect URL."""
        req = self._read(state, "state")
        if req is None:
            raise ValueError("sign-in link expired, please try connecting again")
        code = self._sign("code", CODE_TTL, client_id=req["client_id"], email=email,
                          redirect_uri=req["redirect_uri"], explicit=req["explicit"], challenge=req["challenge"],
                          scopes=req["scopes"], resource=req.get("resource"))
        return construct_redirect_uri(req["redirect_uri"], code=code, state=req.get("client_state"))

    async def load_authorization_code(self, client: OAuthClientInformationFull,
                                      authorization_code: str) -> AuthorizationCode | None:
        c = self._read(authorization_code, "code")
        if not c or c["client_id"] != client.client_id:
            return None
        return AuthorizationCode(code=authorization_code, scopes=c["scopes"], expires_at=c["exp"],
                                 client_id=c["client_id"], code_challenge=c["challenge"],
                                 redirect_uri=AnyUrl(c["redirect_uri"]), redirect_uri_provided_explicitly=c["explicit"],
                                 resource=c.get("resource"), subject=c["email"])

    def _issue(self, client_id: str, email: str, scopes: list[str], resource: str | None) -> OAuthToken:
        common = {"client_id": client_id, "sub": email, "scopes": scopes, "resource": resource}
        return OAuthToken(access_token=self._sign("access", ACCESS_TTL, **common), token_type="Bearer",
                          expires_in=ACCESS_TTL, scope=" ".join(scopes),
                          refresh_token=self._sign("refresh", REFRESH_TTL, **common))

    async def exchange_authorization_code(self, client: OAuthClientInformationFull,
                                          authorization_code: AuthorizationCode) -> OAuthToken:
        return self._issue(client.client_id, authorization_code.subject, authorization_code.scopes,
                           authorization_code.resource)

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str) -> RefreshToken | None:
        c = self._read(refresh_token, "refresh")
        if not c or c["client_id"] != client.client_id:
            return None
        return RefreshToken(token=refresh_token, client_id=c["client_id"], scopes=c["scopes"], expires_at=c["exp"],
                            resource=c.get("resource"), subject=c["sub"])

    async def exchange_refresh_token(self, client: OAuthClientInformationFull, refresh_token: RefreshToken,
                                     scopes: list[str]) -> OAuthToken:
        return self._issue(client.client_id, refresh_token.subject, scopes or refresh_token.scopes,
                           refresh_token.resource)

    async def load_access_token(self, token: str) -> AccessToken | None:
        if (c := self._read(token, "service")) is not None:
            return AccessToken(token=token, client_id=c["client_id"], scopes=[SCOPE], expires_at=c["exp"])
        c = self._read(token, "access")
        if c is None:
            return None
        return AccessToken(token=token, client_id=c["client_id"], scopes=c["scopes"], expires_at=c["exp"],
                           resource=c.get("resource"), subject=c["sub"])

    async def revoke_token(self, token) -> None:
        # Tokens are short-lived JWTs; revoking would need a deny-list, which a demo doesn't warrant.
        return None
