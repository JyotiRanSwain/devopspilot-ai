"""Application settings, read from environment variables (prefix DOP_) or a .env file."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="DOP_", extra="ignore")

    # Web server
    host: str = "127.0.0.1"
    port: int = 8000
    api_token: str = ""  # empty = no auth, only acceptable on loopback
    allowed_origins: str = "http://127.0.0.1:8000,http://localhost:8000"
    max_request_bytes: int = 64_000

    # Storage
    db_path: str = "data/devopspilot.db"

    # Docker
    docker_host: str = ""  # e.g. tcp://docker-proxy:2375; empty = SDK default
    max_containers: int = 200
    log_max_lines: int = 1000
    log_max_bytes: int = 1_000_000

    # AI (optional): none | openai | bedrock
    ai_provider: str = "none"
    ai_model: str = ""
    ai_base_url: str = "https://api.openai.com/v1"
    ai_api_key: str = ""
    ai_timeout_seconds: float = 30.0
    ai_max_tokens: int = 1500

    # AWS (optional, read-only, disabled until enabled)
    aws_enabled: bool = False
    aws_region: str = ""
    aws_profile: str = ""

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def is_loopback(self) -> bool:
        return self.host in LOOPBACK_HOSTS

    def check_safe_binding(self) -> None:
        """Refuse to listen on a non-loopback address without an API token."""
        if not self.is_loopback and not self.api_token:
            raise SystemExit(
                f"Refusing to bind to {self.host} without DOP_API_TOKEN. "
                "Set a token, or use DOP_HOST=127.0.0.1."
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()
