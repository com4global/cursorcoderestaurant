from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/restarentai"
    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24
    cors_origins: str = "http://localhost:5173"
    llm_enabled: bool = False
    openai_api_key: str | None = None

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
