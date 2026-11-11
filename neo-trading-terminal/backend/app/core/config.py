import os
import secrets
from typing import Literal
from pathlib import Path
from urllib.parse import urlparse

from pydantic import BaseModel, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Instrument(BaseModel):
    exchange_segment: Literal["nse_cm", "bse_cm", "nse_fo", "bse_fo", "cde_fo", "mcx_fo"]
    instrument_token: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9 _.-]+$")


PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    app_name: str = "Neo Trading Terminal"
    environment: Literal["development", "test", "production"] = "development"
    trading_mode: Literal["paper", "live"] = "paper"
    live_trading_enabled: bool = False
    frontend_url: str = "http://localhost:3000"
    app_password: SecretStr | None = None
    jwt_secret: str = ""
    data_dir: Path = PROJECT_ROOT / "data"
    paper_starting_balance: int = 100000
    market_data_source: Literal["sample", "kotak"] = "sample"
    kotak_instruments: list[Instrument] = Field(default_factory=list, max_length=50)
    kotak_consumer_key: SecretStr | None = None
    kotak_ucc: str | None = None
    kotak_mobile_number: str | None = None
    kotak_mpin: SecretStr | None = None
    kotak_environment: str = "prod"
    openai_api_key: SecretStr | None = None
    gemini_api_key: SecretStr | None = None
    openai_backup_api_key: SecretStr | None = None
    gemini_backup_api_key: SecretStr | None = None
    options_agent_provider: Literal['auto', 'gemini', 'openai', 'ollama'] = 'ollama'
    options_agent_model: str | None = Field(default=None, min_length=1, max_length=128,
                                          pattern=r'^[A-Za-z0-9_.:-]+$')
    ollama_base_url: str = 'http://localhost:11434/v1'
    ollama_api_key: SecretStr = SecretStr('ollama')
    ollama_reasoning_effort: Literal['none', 'low', 'medium', 'high'] | None = 'none'
    ollama_timeout_seconds: int = Field(default=90, ge=5, le=600)
    options_agent_stream: bool = True
    options_agent_enabled: bool = True
    analytics_tools_enabled: bool = False
    agent_input_token_estimate_limit: int = Field(default=24000, ge=1)
    agent_context_token_limit: int = Field(default=32768, ge=1)
    options_mcp_port: int = Field(default=8766, ge=0, le=65535)
    external_mcp_config: Path = PROJECT_ROOT / 'mcp.json'

    @model_validator(mode='after')
    def _validate_ollama_url(self):
        raw = (self.ollama_base_url or '').strip().rstrip('/')
        parsed = urlparse(raw)
        if parsed.scheme != 'http' or parsed.hostname not in {'localhost', '127.0.0.1', '::1'} or not parsed.netloc:
            raise ValueError('OLLAMA_BASE_URL must be an http loopback URL (localhost, 127.0.0.1, or ::1)')
        self.ollama_base_url = raw
        return self

    @model_validator(mode='after')
    def _validate_agent_context(self):
        if self.agent_input_token_estimate_limit + 4096 > self.agent_context_token_limit:
            raise ValueError('Agent input estimate plus generation must fit context limit')
        return self

    @model_validator(mode="after")
    def _ensure_persistent_jwt_secret(self) -> "Settings":
        if self.jwt_secret and self.jwt_secret.strip():
            self.jwt_secret = self.jwt_secret.strip()
            return self
        secret_file = self.data_dir / ".jwt_secret"
        try:
            if secret_file.exists():
                existing = secret_file.read_text(encoding="utf-8").strip()
                if existing:
                    self.jwt_secret = existing
                    return self
        except OSError:
            pass
        generated = secrets.token_urlsafe(32)
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            fd = os.open(secret_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                os.write(fd, generated.encode("utf-8"))
            finally:
                os.close(fd)
            try:
                os.chmod(secret_file, 0o600)
            except OSError:
                pass
        except FileExistsError:
            try:
                existing = secret_file.read_text(encoding="utf-8").strip()
                if existing:
                    self.jwt_secret = existing
                    return self
            except OSError:
                pass
        except OSError:
            pass
        self.jwt_secret = generated
        return self

    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env", PROJECT_ROOT / "backend" / ".env"),
        env_file_encoding="utf-8", extra="ignore"
    )


settings = Settings()
