from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings


class AgentSettings(BaseSettings):
    """Configuration 12-factor de l'agent (préfixe ELYON_AGENT_)."""

    model_config = {"env_prefix": "ELYON_AGENT_", "extra": "ignore"}

    server_url: str = "http://localhost:8000"
    state_file: Path = Path("/var/lib/elyon-player/state.json")
    data_dir: Path = Path("/var/lib/elyon-player")
    agent_version: str = "0.1.0"
    request_timeout_seconds: float = 15.0
    command_poll_seconds: int = 5
    widgets_feed_refresh_seconds: int = 300
    enroll_ttl_seconds: int = 600
    serial: str | None = None
    name: str | None = None
    enroll_code: str | None = None
    enroll_code_file: Path | None = None
    enroll_wait_seconds: int = 300
