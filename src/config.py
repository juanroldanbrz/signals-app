from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # LLM — set llm_api_key for API-key providers (Gemini, OpenAI, Anthropic…)
    # For Vertex AI leave llm_api_key empty and set the three vertexai_* fields instead
    llm_api_key: str = ""
    llm_model: str = "gemini/gemini-2.5-flash"
    # Vertex AI (optional — only needed when llm_model starts with "vertex_ai/")
    vertexai_project: str = ""
    vertexai_location: str = "us-central1"
    vertexai_credentials: str = ""   # full contents of the service-account JSON
    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db: str = "signals"
    default_interval_minutes: int = 60
    jwt_secret: str
    jwt_expire_minutes: int = 60 * 24 * 7
    mandatory_email_verification: bool = False
    resend_api_key: str = ""
    brave_search_api_key: str = ""
    brightdata_wss: str = ""
    premium_domains: str = "skyscanner.com,skyscanner.net"
    # Langfuse (optional — tracing disabled if not set)
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"


settings = Settings()
