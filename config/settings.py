from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Groq
    groq_api_key: str
    groq_orchestrator_model: str = "llama-3.3-70b-versatile"
    groq_agent_model: str = "llama-3.1-8b-instant"
    groq_max_tokens: int = 1024

    # OpenRouter
    openrouter_api_key: str
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_embedding_model: str = "text-embedding-3-small"

    # Kapruka MCP
    kapruka_mcp_base_url: str = "https://mcp.kapruka.com"
    kapruka_default_currency: str = "LKR"
    kapruka_cache_ttl_seconds: int = 1800

    # Rate limits
    rate_limit_requests_per_minute: int = 60
    rate_limit_create_order_per_hour: int = 30

    # Database
    database_url: str

    # pgvector
    vector_dimensions: int = 1536
    vector_similarity_threshold: float = 0.75
    vector_top_k: int = 5

    # Auth
    jwt_secret: str
    jwt_expires_in_days: int = 7

    # Server
    port: int = 8000
    env: str = "development"
    log_level: str = "DEBUG"

    # Memory
    max_short_term_turns: int = 20
    max_episodic_inject_count: int = 5
    max_semantic_profile_tokens: int = 300

    @property
    def is_dev(self) -> bool:
        return self.env == "development"


settings = Settings()
