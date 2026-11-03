import secrets
from typing import Literal
from pathlib import Path

from pydantic import BaseModel, Field, SecretStr
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
    jwt_secret: str = Field(default_factory=lambda: secrets.token_urlsafe(32))
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
    options_agent_provider: Literal['auto', 'gemini', 'openai'] = 'auto'
    options_agent_model: str | None = Field(default=None, min_length=1, max_length=128,
                                          pattern=r'^[A-Za-z0-9_.:-]+$')
    options_agent_enabled: bool = True
    options_mcp_port: int = Field(default=8766, ge=0, le=65535)
    external_mcp_config: Path = PROJECT_ROOT / 'mcp.json'

    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env", PROJECT_ROOT / "backend" / ".env"),
        env_file_encoding="utf-8", extra="ignore"
    )


settings = Settings()
