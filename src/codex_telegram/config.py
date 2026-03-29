from __future__ import annotations

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    telegram_bot_token: str = Field(alias="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: int = Field(alias="TELEGRAM_CHAT_ID")
    codex_allowed_root: Path = Field(alias="CODEX_ALLOWED_ROOT")
    codex_default_cwd: Path | None = Field(default=None, alias="CODEX_DEFAULT_CWD")
    codex_model: str | None = Field(default=None, alias="CODEX_MODEL")
    codex_profile: str | None = Field(default=None, alias="CODEX_PROFILE")
    codex_sandbox: str = Field(default="workspace-write", alias="CODEX_SANDBOX")
    codex_enable_web_search: bool = Field(
        default=False,
        alias="CODEX_ENABLE_WEB_SEARCH",
    )
    codex_store_path: Path = Field(
        default=Path(".codex-telegram/state.json"),
        alias="CODEX_STORE_PATH",
    )
    codex_progress_updates: bool = Field(
        default=True,
        alias="CODEX_PROGRESS_UPDATES",
    )
    codex_loader_gif_url: str = Field(
        default="https://media.giphy.com/media/pY8jLmZw0ElqvVeRH4/giphy.gif",
        alias="CODEX_LOADER_GIF_URL",
    )
    codex_timeout_seconds: int = Field(
        default=900,
        alias="CODEX_TIMEOUT_SECONDS",
    )
    codex_log_level: str = Field(default="INFO", alias="CODEX_LOG_LEVEL")
    codex_log_file: Path = Field(
        default=Path(".codex-telegram/bot.log"),
        alias="CODEX_LOG_FILE",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("codex_allowed_root", mode="before")
    @classmethod
    def _expand_allowed_root(cls, value: str | Path) -> Path:
        return Path(value).expanduser().resolve()

    @field_validator("codex_default_cwd", mode="before")
    @classmethod
    def _expand_default_cwd(cls, value: str | Path | None) -> Path | None:
        if value in (None, ""):
            return None
        return Path(value).expanduser().resolve()

    @field_validator("codex_store_path", mode="before")
    @classmethod
    def _expand_store_path(cls, value: str | Path) -> Path:
        return Path(value).expanduser()

    @field_validator("codex_log_file", mode="before")
    @classmethod
    def _expand_log_file(cls, value: str | Path) -> Path:
        return Path(value).expanduser()

    @field_validator("codex_default_cwd")
    @classmethod
    def _validate_default_cwd(cls, value: Path | None, info) -> Path | None:
        allowed_root = info.data.get("codex_allowed_root")
        if value is None:
            return allowed_root
        if allowed_root is not None and allowed_root not in value.parents and value != allowed_root:
            raise ValueError("CODEX_DEFAULT_CWD must be inside CODEX_ALLOWED_ROOT")
        return value

    @property
    def store_path(self) -> Path:
        return self.codex_store_path
