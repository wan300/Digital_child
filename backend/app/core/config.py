from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    api_prefix: str = "/api"
    project_name: str = "Human Memory Orchestrator"
    backend_cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )

    admin_username: str = "admin"
    admin_password: str = "12345678"
    user_username: str = "user"
    user_password: str = "12345678"
    jwt_secret: str = "replace-with-a-long-random-secret"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24

    database_url: str = "sqlite+aiosqlite:///./data/app.db"
    redis_url: str = "redis://localhost:6379/0"

    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    chat_model: str = "gpt-4o"
    memory_model: str = "gpt-4o-mini"
    graph_model: str = "gpt-4o-mini"
    embedding_model: str = "text-embedding-3-large"
    embedding_dim: int = 3072

    letta_base_url: str = "http://localhost:8283"
    letta_api_key: str = ""
    letta_server_password: str = "local-letta-password"

    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "letmemgraph"
    qdrant_url: str = "http://localhost:6333"

    lightrag_base_url: str = "http://localhost:9621"
    lightrag_api_key: str = "local-lightrag-key"

    data_dir: Path = Path("data")
    max_memories_per_context: int = 8
    max_timeline_facts_per_context: int = 8
    max_document_chunks_per_context: int = 5
    simulation_step_minutes: int = 720
    simulation_max_agents_per_step: int = 2
    simulation_snapshot_interval: int = 5
    simulation_worker_interval_seconds: float = 5.0
    simulation_concordia_enabled: bool = True
    simulation_use_letta_actions: bool = False
    simulation_concordia_max_tokens: int = 1200
    simulation_external_gm_timeout_seconds: float = 35.0
    simulation_direct_llm_timeout_seconds: float = 20.0
    simulation_step_lock_timeout_seconds: int = 180

    @field_validator("backend_cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()
