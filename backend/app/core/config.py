from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")
    database_url: str = "sqlite:///./storage/reconcile.db"
    redis_url: str = "redis://127.0.0.1:6379/0"
    worker_backend: str = "local"
    storage_path: str = "./storage"
    parser: str = "docling"
    docling_pipeline: str = "standard"
    max_upload_mb: int = 50
    max_pages: int = 500
    openai_api_key: str = ""
    openai_base_url: str = ""
    openai_model: str = "gpt-4o"
    openai_vision_model: str = "gpt-4o"
    openai_embedding_model: str = "text-embedding-3-small"
    openai_embedding_dimensions: int = 1536
    invoice_azure_endpoint: str = ""
    invoice_azure_api_key: str = ""
    invoice_azure_deployment: str = ""
    enable_embeddings: bool = False
    enable_dual_augmentation: bool = True
    enable_vision_fallback: bool = True
    enable_human_review: bool = True
    max_agent_tool_calls: int = 12
    default_price_tolerance_percent: str = "2"
    rounding_tolerance: str = "0.02"
    api_token: str = ""
    organization_id: str = "local"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    ai_timeout_seconds: int = 60
    job_timeout_seconds: int = 1800
    local_worker_poll_seconds: float = 1.0

    @property
    def storage(self) -> Path:
        path = Path(self.storage_path)
        return path if path.is_absolute() else ROOT / path

    @property
    def ai_configured(self) -> bool:
        return bool(
            self.openai_api_key or (self.invoice_azure_api_key and self.invoice_azure_endpoint)
        )


settings = Settings()
