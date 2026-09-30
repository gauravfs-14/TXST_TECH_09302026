"""Runtime settings. Everything is overridable via environment variables prefixed CONFIANCE_."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CONFIANCE_", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./confiance.db"
    blob_dir: str = "./data/blobs"
    secrets_file: str = "./data/secrets.json"

    # One OpenAI-compatible endpoint powers every internal agent AND the assistant we test against.
    # Works with OpenAI, Ollama (http://localhost:11434/v1), OpenRouter, Groq, LM Studio, vLLM, ...
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str | None = None
    llm_model: str = ""
    llm_worker_model: str = ""  # optional cheaper model for simple jobs; defaults to llm_model
    llm_timeout_s: float = 300.0  # max silence between streamed chunks
    llm_max_concurrency: int = 4  # simultaneous AI calls (free tiers and local GPUs want this low)
    llm_rpm: int = 0  # max AI calls per minute; 0 = no client-side limit (retries still back off on 429)
    llm_reasoning_effort: str = ""  # "" = provider default. We never turn thinking down on our own.

    # Defaults for optional extra engine adapters (claude, gemini). The "openai" engine uses llm_model.
    engine_models: dict[str, str] = {
        "claude": "claude-opus-5-5",
        "gemini": "gemini-2.5-flash",
        "offline": "offline-sim-1",
    }

    # Search used for controlled (injectable) mode: duckduckgo (no key) | searxng | tavily | brave | offline
    search_provider: str = "duckduckgo"
    searxng_url: str | None = None
    tavily_api_key: str | None = None
    brave_api_key: str | None = None

    # Offline engine/search are test fixtures and must be opted into explicitly.
    allow_offline: bool = False

    # Simulation defaults
    samples_per_question: int = 3
    max_engine_steps: int = 6
    max_parallel_calls: int = 6
    use_llm_judge: bool = False  # extra AI call per answer; off by default to save quota (deterministic metrics stay on)

    # Drift monitor
    drift_interval_minutes: int = 24 * 60
    drift_canary_samples: int = 3

    # Post-deploy measurement delay (engines need time to recrawl)
    post_deploy_measure_after_hours: int = 72

    # Notifications
    slack_webhook_url: str | None = None
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    alert_email_from: str | None = None
    alert_email_to: str | None = None

    enable_scheduler: bool = True

    # Built web app (frontend/dist). When the folder exists the API serves the whole product from one port.
    static_dir: str = "../frontend/dist"
    # Extra browser origins allowed to call the API (only needed when the UI is served from somewhere else).
    cors_origins: list[str] = ["http://localhost:5173"]


@lru_cache
def get_settings() -> Settings:
    return Settings()


# USD per 1M tokens (input, output). Used for the cost ledger; unknown models log tokens with cost 0.
PRICING: dict[str, tuple[float, float]] = {
    "claude-opus-5-5": (4.0, 20.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-haiku-4-5": (1.0, 5.0),
}
