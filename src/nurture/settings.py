"""Application configuration.

Loaded once at startup via pydantic-settings. Per DESIGN.md Section 11,
the app must refuse to start if any required variable is missing — that
is the default pydantic-settings behaviour (ValidationError on import).
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]

SendMode = Literal["dry_run", "shadow", "live"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Required, no default (DESIGN.md Section 11) ---
    anthropic_api_key: str
    ghl_token: str
    ghl_location_id: str
    webhook_secret: str = Field(min_length=32)
    admin_secret: str
    database_url: str
    webinar_link: str
    session_when: str

    # --- Optional, with defaults ---
    claude_model: str = "claude-sonnet-5"
    ghl_base_url: str = "https://services.leadconnectorhq.com"
    ghl_api_version: str = "2021-07-28"
    send_mode: SendMode = "dry_run"
    bot_enabled: bool = True
    session_name: str = "AUM Strategic Diagnostic"
    session_cost: str = "free"
    debounce_seconds: int = 20
    window_safety_hours: float = 23.5
    max_bot_turns: int = 10
    max_diagnosis_turns: int = 3
    escalation_message: str = (
        "Thanks, let me get someone from the OAWA team to pick this up with you personally."
    )
    optout_message: str = "Understood, you won't receive any more messages from us. Take care!"
    retention_days: int = 180
    log_level: str = "INFO"

    # --- File-based config (DESIGN.md Section 11) ---
    config_dir: Path = REPO_ROOT / "config"
    prompts_dir: Path = REPO_ROOT / "prompts"

    @field_validator("send_mode", mode="before")
    @classmethod
    def _normalise_send_mode(cls, v: str) -> str:
        return v.lower() if isinstance(v, str) else v

    def agenda_is_filled_in(self) -> bool:
        """False if config/agenda.yaml still contains the placeholder.

        DESIGN.md Section 11: the app must refuse to start in shadow/live
        mode while agenda.yaml still says FILL IN. Phase 4 (the engine that
        actually renders the agenda into the prompt) is not built yet, so
        this is exposed as a plain check other code / startup logic can use,
        rather than enforced here.
        """
        agenda_path = self.config_dir / "agenda.yaml"
        if not agenda_path.exists():
            return False
        data = yaml.safe_load(agenda_path.read_text()) or {}
        items = data.get("agenda", [])
        return bool(items) and "FILL IN" not in items

    def require_agenda_filled_in(self) -> None:
        if self.send_mode in ("shadow", "live") and not self.agenda_is_filled_in():
            raise RuntimeError(
                "config/agenda.yaml still contains the FILL IN placeholder. "
                "SEND_MODE=shadow/live requires a real session agenda "
                "(DESIGN.md Section 11, Q4)."
            )


def get_settings() -> Settings:
    """Construct Settings fresh (no caching) so tests can override env vars."""
    return Settings()
