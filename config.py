from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    DATABASE_URL: str = "postgresql://amc:amc_password@localhost:5432/amccompass"

    # --- LLM provider (OpenAI-compatible: Qwen via OpenRouter/Groq/Together/DashScope, or local Ollama) ---
    LLM_PROVIDER: str = "openai"  # "openai" (OpenAI-compatible, default) or "anthropic" (legacy)
    LLM_BASE_URL: str = "http://localhost:11434/v1"  # hosted: https://openrouter.ai/api/v1 ; default = local Ollama
    LLM_API_KEY: str = "ollama"  # any non-empty value for local Ollama; real key for hosted Qwen
    LLM_MODEL: str = "qwen2.5:7b-instruct-q4_K_M"  # MCQ / extraction / note-verify model
    LLM_TUTOR_MODEL: str = ""  # optional separate tutor model; falls back to LLM_MODEL when empty

    JWT_SECRET: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days
    ENVIRONMENT: str = "development"
    FRONTEND_URL: str = "http://localhost:3000"
    UPLOAD_DIR: str = "uploads"

    # --- Anthropic (legacy, kept for easy switch-back: set LLM_PROVIDER=anthropic) ---
    ANTHROPIC_API_KEY: str = ""
    TUTOR_MODEL: str = "claude-sonnet-4-20250514"
    MCQ_FALLBACK_MODEL: str = "claude-haiku-3-5-20241022"

    # Freemium limits
    FREE_DAILY_MCQ_LIMIT: int = 10
    FREE_DAILY_AI_LIMIT: int = 5

    @property
    def async_database_url(self) -> str:
        url = self.DATABASE_URL
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return url

    @property
    def sync_database_url(self) -> str:
        url = self.DATABASE_URL
        if url.startswith("postgresql+asyncpg://"):
            return url.replace("postgresql+asyncpg://", "postgresql://", 1)
        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
