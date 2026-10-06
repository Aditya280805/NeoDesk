from typing import Any, NoReturn
from datetime import UTC, datetime
from math import isfinite
from threading import RLock
from time import monotonic
import re

from app.brokers.base_broker import BrokerError, BrokerInterface
from app.core.config import Settings


class KotakNeoBroker(BrokerInterface):
    """SDK adapter: market data and local login; live execution stays disabled."""

    def __init__(self, config: Settings, client_factory=None):
        self.config = config
        self._factory = client_factory
        self._client = None
        self._authenticated = False
        self._lock = RLock()
        self._cache = None
        self._cache_until = 0.0

    def _sdk(self):
        if self._client is None:
            key = self.config.kotak_consumer_key
            if key is None or not key.get_secret_value().strip():
                raise BrokerError("Set KOTAK_CONSUMER_KEY in the project .env file.")
            factory = self._factory
            if factory is None:
                from neo_api_client import NeoAPI
                factory = NeoAPI
            self._client = factory(
                consumer_key=key.get_secret_value(),
                environment=self.config.kotak_environment, timeout=10.0,
            )
        return self._client

    @staticmethod
    def _check_login(response, kind):
        data = response.get("data") if isinstance(response, dict) else None
        if (not isinstance(data, dict) or data.get("status") != "success"
                or data.get("kType") != kind or not data.get("token") or not data.get("sid")):
            raise BrokerError("Kotak login failed. Check credentials and use a fresh TOTP.")

    def login(self, totp: str, mpin: str) -> None:
        with self._lock:
            self.close()
            if not re.fullmatch(r"[0-9]{6}", totp) or not re.fullmatch(r"[0-9]{6}", mpin):
                raise BrokerError("TOTP and MPIN must each contain six digits.")
            if not self.config.kotak_mobile_number or not self.config.kotak_ucc:
                raise BrokerError("Set KOTAK_MOBILE_NUMBER and KOTAK_UCC in .env first.")
            try:
                client = self._sdk()
                self._check_login(client.totp_login(
                    mobile_number=self.config.kotak_mobile_number,
                    ucc=self.config.kotak_ucc, totp=totp,
                ), "View")
                self._check_login(client.totp_validate(mpin=mpin), "Trade")
                self._authenticated = True
            except Exception:
                self.close()
                raise BrokerError("Kotak login failed. Check credentials and use a fresh TOTP.") from None

    def close(self) -> None:
        with self._lock:
            client, self._client = self._client, None
            authenticated, self._authenticated = self._authenticated, False
            self._cache = None
            self._cache_until = 0.0
            if client is not None:
                try:
                    if authenticated:
                        client.logout()
                except Exception:
                    pass
                finally:
                    client.api_client.rest_client.close()

    @property
    def name(self) -> str:
        return "kotak-neo"

    @property
    def is_authenticated(self) -> bool:
        return self._authenticated

    def _disabled(self) -> NoReturn:
        raise BrokerError("Live account/order access is disabled; use the paper order endpoints.")

    def get_quotes(self, strict=True) -> list[dict[str, Any]]:
        with self._lock:
            if not self.config.kotak_instruments:
                raise BrokerError("Configure KOTAK_INSTRUMENTS using tokens from the instrument master.")
            if self._cache is not None and monotonic() < self._cache_until:
                return [dict(row) for row in self._cache]
            try:
                raw = self._sdk().quotes(
                    instrument_tokens=[item.model_dump() for item in self.config.kotak_instruments],
                    quote_type="all",
                )
                if not isinstance(raw, list) or not raw:
                    raise ValueError("Unexpected quote response")
                expected = {(i.exchange_segment, i.instrument_token) for i in self.config.kotak_instruments}
                seen = set()
                normalized = []
                for row in raw:
                    pair = (row["exchange"], str(row["exchange_token"]))
                    if pair not in expected or pair in seen:
                        raise ValueError("Invalid quote")
                    seen.add(pair)
                    try:
                        ltp, change = float(row['ltp']), float(row['per_change'])
                        if not isfinite(ltp) or ltp <= 0 or not isfinite(change):
                            raise ValueError('Unpriced instrument')
                    except (KeyError,ValueError,TypeError):
                        if strict:
                            raise
                        continue
                    def optional_number(key):
                        try:
                            value=float(row.get(key))
                            return value if isfinite(value) and value>=0 else None
                        except (ValueError,TypeError):
                            return None
                    volume, vwap=optional_number('last_volume'),optional_number('avg_cost')
                    normalized.append({
                        "symbol": str(row["display_symbol"]), "ltp": ltp, "change_pct": change,
                        "source": "kotak", "exchange_segment": pair[0], "instrument_token": pair[1],
                        "received_at": datetime.now(UTC).isoformat(),
                        "last_trade_time": row.get("lstup_time"),
                        "volume":volume, "vwap":vwap,
                        "change":optional_number('change') if change>=0 else -abs(float(row.get('change',0))),
                        "ohlc":{k:float(v) for k,v in row.get('ohlc',{}).items() if k in ('open','high','low','close') and v is not None and str(v).replace('.','',1).isdigit()},
                        "turnover_estimate":volume*vwap if volume is not None and vwap is not None else None,
                    })
                if strict and seen != expected:
                    raise ValueError("Incomplete quotes")
                self._cache = normalized
                self._cache_until = monotonic() + 2.0
                return [dict(row) for row in normalized]
            except BrokerError:
                raise
            except Exception as exc:
                self._cache = None
                if 'connect' in str(exc).lower() or '10013' in str(exc):
                    raise BrokerError('Kotak quotes unavailable: network connection blocked or unreachable. Restart the server with network access.') from None
                raise BrokerError("Kotak quotes unavailable. Check token, instruments, connection or broker rate limits.") from None

    def get_positions(self) -> list[dict[str, Any]]:
        self._disabled()

    def get_orders(self) -> list[dict[str, Any]]:
        self._disabled()

    def place_order(self, order: dict[str, Any]) -> dict[str, Any]:
        self._disabled()

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        self._disabled()
