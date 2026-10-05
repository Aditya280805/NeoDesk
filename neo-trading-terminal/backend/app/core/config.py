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
    data_dir: Path = PROJECT_ROOT / "data"
    paper_starting_balance: int = 100000
    market_data_source: Literal["sample", "kotak"] = "sample"
    kotak_instruments: list[Instrument] = Field(default_factory=list, max_length=50)
    kotak_consumer_key: SecretStr | None = None
    kotak_ucc: str | None = None
    kotak_mobile_number: str | None = None
    kotak_mpin: SecretStr | None = None
    kotak_environment: str = "prod"

    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env", PROJECT_ROOT / "backend" / ".env"),
        env_file_encoding="utf-8", extra="ignore"
    )


settings = Settings()
