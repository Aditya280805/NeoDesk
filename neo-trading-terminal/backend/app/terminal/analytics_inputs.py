"""Bounded declared historical inputs; user imports never become live verification."""
import hashlib
import math
from typing import Literal
from zoneinfo import ZoneInfo
from uuid import UUID, uuid4

from pydantic import AwareDatetime, Field, model_validator

from .analytics_contracts import Contract
from .options_snapshot import OptionsContext


class HistoricalBar(Contract):
    time: AwareDatetime
    open: float = Field(gt=0, allow_inf_nan=False)
    high: float = Field(gt=0, allow_inf_nan=False)
    low: float = Field(gt=0, allow_inf_nan=False)
    close: float = Field(gt=0, allow_inf_nan=False)
    volume: float | None = Field(default=None, ge=0, allow_inf_nan=False)

    @model_validator(mode='after')
    def prices(self):
        if not self.low <= min(self.open, self.close) <= max(self.open, self.close) <= self.high:
            raise ValueError('Contradictory OHLC')
        return self


class HistoricalAnalyticsInput(Contract):
    schema_version: Literal['analytics-input.1'] = 'analytics-input.1'
    context: OptionsContext
    provenance: str = Field(min_length=1, max_length=1000)
    licence: str = Field(min_length=1, max_length=1000)
    observed_at: AwareDatetime
    bars: tuple[HistoricalBar, ...] = Field(default=(), max_length=500)
    vix_history: tuple[float, ...] = Field(default=(), max_length=500)
    return_dates: tuple[AwareDatetime, ...] = Field(default=(), max_length=5000)
    cash_flow_adjusted_returns: tuple[float, ...] = Field(default=(), max_length=5000)
    return_frequency: Literal['daily'] = 'daily'
    benchmark_returns: tuple[float, ...] = Field(default=(), max_length=5000)
    bank_returns: tuple[float, ...] = Field(default=(), max_length=5000)

    @model_validator(mode='after')
    def aligned(self):
        if not self.bars and not self.cash_flow_adjusted_returns:
            raise ValueError('At least one historical series required')
        for times in (tuple(bar.time for bar in self.bars), self.return_dates):
            if any(a >= b for a, b in zip(times, times[1:])) or times and times[-1] > self.observed_at:
                raise ValueError('Ordered nonfuture observations required')
        if len(self.return_dates) != len(self.cash_flow_adjusted_returns):
            raise ValueError('Dated returns required')
        days = [value.astimezone(ZoneInfo('Asia/Kolkata')).date() for value in self.return_dates]
        if len(set(days)) != len(days):
            raise ValueError('Return series requires at most one observation per trading day')
        for series in (self.cash_flow_adjusted_returns, self.benchmark_returns, self.bank_returns):
            if any(not math.isfinite(value) or value <= -1 for value in series):
                raise ValueError('Invalid simple returns')
        if any(not math.isfinite(value) or value <= 0 for value in self.vix_history):
            raise ValueError('Invalid VIX observations')
        if self.vix_history and len(self.vix_history) != len(self.bars):
            raise ValueError('VIX must align to declared bars')
        if any(series and len(series) != len(self.return_dates) for series in (self.benchmark_returns, self.bank_returns)):
            raise ValueError('Benchmark alignment required')
        return self


class AnalyticsInputStore:
    def __init__(self, store):
        self.store = store
        with store.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS analytics_inputs (id TEXT PRIMARY KEY, owner INTEGER NOT NULL, checksum TEXT NOT NULL, payload TEXT NOT NULL)')

    def save(self, owner, value):
        if type(owner) is not int or owner <= 0:
            raise ValueError('Authenticated owner required')
        value = HistoricalAnalyticsInput.model_validate(value)
        encoded = value.model_dump_json()
        identity = str(uuid4())
        checksum = hashlib.sha256(encoded.encode()).hexdigest()
        with self.store.connect() as db:
            db.execute('INSERT INTO analytics_inputs VALUES (?,?,?,?)', (identity, owner, checksum, encoded))
        return dict(dataset_id=identity, checksum=checksum, provenance=value.provenance, live_verification='unverified')

    def load(self, owner, identity, context):
        if type(owner) is not int or owner <= 0:
            raise ValueError('Authenticated owner required')
        identity = str(UUID(str(identity)))
        with self.store.connect() as db:
            row = db.execute('SELECT checksum,payload FROM analytics_inputs WHERE owner=? AND id=?', (owner, identity)).fetchone()
        if row is None:
            raise ValueError('Input dataset unavailable')
        if hashlib.sha256(row[1].encode()).hexdigest() != row[0]:
            raise ValueError('Input dataset integrity mismatch')
        value = HistoricalAnalyticsInput.model_validate_json(row[1])
        if value.context != context:
            raise ValueError('Input dataset market context differs')
        inputs = {}
        if value.bars:
            inputs.update(bars=[bar.model_dump(mode='json') for bar in value.bars], vix_history=list(value.vix_history))
        if value.cash_flow_adjusted_returns:
            inputs['verified_returns'] = list(value.cash_flow_adjusted_returns)
            if value.benchmark_returns:
                inputs['benchmark_returns'] = list(value.benchmark_returns)
            if value.bank_returns:
                inputs['bank_returns'] = list(value.bank_returns)
        return inputs, f'user-import:{identity}:{row[0]}', value
