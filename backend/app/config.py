from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    deepseek_api_key: SecretStr = SecretStr("")
    deepseek_model: str = "deepseek-v4-flash"
    deepseek_base_url: str = "https://api.deepseek.com"
    model_timeout_seconds: float = Field(45, gt=0)
    run_timeout_seconds: float = Field(120, gt=0)
    max_iterations: int = Field(6, ge=1, le=30)
    database_path: str = "data/agent.sqlite3"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    heartbeat_seconds: float = Field(15, ge=0.1)
    development_user_id: str = Field("demo_researcher", min_length=1, max_length=160)
    document_storage_path: str = "data/documents"
    max_upload_bytes: int = Field(20 * 1024 * 1024, ge=1024, le=1024 * 1024 * 1024)
    max_pdf_pages: int = Field(500, ge=1, le=5000)
    max_extracted_chars: int = Field(2_000_000, ge=1000)
    max_chunks_per_document: int = Field(5000, ge=1)
    chunk_size: int = Field(1200, ge=200, le=12000)
    chunk_overlap: int = Field(180, ge=0, le=4000)
    embedding_provider: str = "sentence_transformers"
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    embedding_version: str = "1"
    embedding_batch_size: int = Field(32, ge=1, le=512)
    reranker_provider: str = "sentence_transformers"
    reranker_model: str = "BAAI/bge-reranker-base"
    reranker_version: str = "1"
    retrieval_timeout_seconds: float = Field(8, gt=0, le=120)
    retrieval_top_k_each: int = Field(20, ge=1, le=100)
    rerank_top_n: int = Field(30, ge=1, le=100)
    evidence_top_k: int = Field(8, ge=1, le=30)
    evidence_max_chars: int = Field(12000, ge=500, le=100000)
    evidence_per_document: int = Field(4, ge=1, le=20)
    rrf_k: int = Field(60, ge=1, le=1000)

    @property
    def model_ready(self):
        return bool(
            self.deepseek_api_key.get_secret_value()
            and self.deepseek_model
            and self.deepseek_base_url.startswith(("http://", "https://"))
        )
