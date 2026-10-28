"""Central configuration, loaded from environment variables (and an optional .env file).

Every external dependency is optional so the service can run in three modes:
  * full     - real LLM + Polygon + Firestore + SEC index
  * demo     - real LLM, bundled demo market data/portfolio (no Polygon/Firestore keys)
  * offline  - scripted fake LLM + demo data (unit tests, CI without secrets)
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

PACKAGE_DIR = Path(__file__).resolve().parent
SERVICE_DIR = PACKAGE_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- LLM -------------------------------------------------------------
    llm_provider: Literal["gemini", "openai", "anthropic", "fake"] = "gemini"
    llm_model: str = "gemini-2.5-flash"
    # Cheaper/faster model used for the guardrail router and the eval judge.
    router_model: str | None = None
    llm_temperature: float = 0.2
    embedding_provider: Literal["gemini", "openai", "hash"] = "gemini"
    embedding_model: str = "models/gemini-embedding-001"

    google_api_key: str | None = None
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None

    # --- Data sources ------------------------------------------------------
    finnhub_api_key: str | None = None
    polygon_api_key: str | None = None
    polygon_base_url: str = "https://api.polygon.io"
    # False in production: never fall back to bundled sample data; report "not configured" instead.
    allow_demo_data: bool = True
    sec_user_agent: str = "BullRunAI research-bot contact@example.com"

    # Firestore (same env vars the existing Flask server uses)
    firebase_service_account: str | None = None
    project_id: str | None = None
    firestore_database: str = "br-prod-db"

    # --- RAG ----------------------------------------------------------------
    index_dir: Path = SERVICE_DIR / "data" / "filings_index"
    index_gcs_uri: str | None = None  # e.g. gs://br-prod-rag/filings_index
    retrieval_k: int = 6

    # --- Agent / API ----------------------------------------------------------
    tools_mode: Literal["local", "mcp"] = "local"
    mcp_server_url: str = "http://localhost:8765/mcp"
    max_history_messages: int = 20
    max_agent_steps: int = 8
    checkpoint_db_url: str | None = None  # postgres://... for durable memory

    google_client_id: str | None = None
    auth_disabled: bool = False  # local dev + demo mode only
    cors_origins: str = "*"

    @property
    def demo_market(self) -> bool:
        return not (self.finnhub_api_key or self.polygon_api_key)

    @property
    def demo_portfolio(self) -> bool:
        # Firestore is used whenever a project is configured; credentials come from
        # FIREBASE_SERVICE_ACCOUNT or, on Cloud Run, the service's own identity.
        return not self.project_id


@lru_cache
def get_settings() -> Settings:
    return Settings()
