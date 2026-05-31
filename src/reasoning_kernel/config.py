"""Single source of truth for configuration and secrets (loaded from env / .env).

Mirrors limolane's `config.settings` convention: every module imports `settings`
from here instead of reading `os.environ` or duplicating defaults. Secrets are
`SecretStr`. Env vars are prefixed `RK_` (e.g. `RK_LLM_PROVIDER_DEFAULT`); provider
keys keep their conventional bare names (`ANTHROPIC_API_KEY`, ...) for familiarity.
"""

from __future__ import annotations

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from env/.env (SSOT)."""

    anthropic_api_key: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices("RK_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"),
    )
    openai_api_key: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices("RK_OPENAI_API_KEY", "OPENAI_API_KEY"),
    )
    deepseek_api_key: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices("RK_DEEPSEEK_API_KEY", "DEEPSEEK_API_KEY"),
    )

    llm_provider_default: str = "anthropic"  # "anthropic" | "openai" | "deepseek" | "fake"
    llm_model_anthropic: str = "claude-sonnet-4-6"  # more capable: "claude-opus-4-8"
    llm_model_openai: str = "gpt-5.5"  # more capable: "gpt-5.5-pro"
    llm_model_deepseek: str = "deepseek-v4-flash"  # more capable: "deepseek-v4-pro"
    deepseek_base_url: str = "https://api.deepseek.com"

    llm_timeout_seconds: float = 120.0
    llm_max_tokens: int = 4096

    model_config = SettingsConfigDict(
        env_prefix="RK_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
