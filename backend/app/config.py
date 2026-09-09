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

    @property
    def model_ready(self):
        return bool(
            self.deepseek_api_key.get_secret_value()
            and self.deepseek_model
            and self.deepseek_base_url.startswith(("http://", "https://"))
        )
