from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/restarentai"
    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24 * 7  # 7 days
    call_order_session_ttl_minutes: int = 60 * 24  # 24 hours
    cors_origins: str = "http://localhost:5173,http://localhost:5174,http://127.0.0.1:5173,http://127.0.0.1:5174,https://zenzeerestaurantai.netlify.app,tauri://localhost,https://tauri.localhost"
    llm_enabled: bool = False
    call_order_llm_orchestrator: bool = False
    ai_call_realtime_enabled: bool = False
    ai_call_provider: str = "vapi"
    ai_call_provider_public_key: str | None = None
    ai_call_provider_assistant_id: str | None = None
    ai_call_provider_assistant_id_en: str | None = None
    ai_call_provider_assistant_id_ta: str | None = None
    ai_call_provider_phone_number_id: str | None = None
    vapi_server_url: str | None = None
    vapi_webhook_secret: str | None = None
    openai_api_key: str | None = None

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
