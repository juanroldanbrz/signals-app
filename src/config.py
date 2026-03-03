from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gemini_api_key: str
    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db: str = "signals"
    default_interval_minutes: int = 60
    # Langfuse (optional — tracing disabled if not set)
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"


settings = Settings()
