"""Versioned public portfolio evidence; transport observations remain internal."""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_serializer

SectionName = Literal['holdings', 'positions', 'orders', 'funds']
SectionState = Literal['available', 'partial', 'unavailable', 'invalid']
IssueCode = Literal[
    'missing_value', 'invalid_number', 'negative_value', 'invalid_row',
    'invalid_envelope', 'payload_limit', 'fetch_failed', 'timeout',
    'identity_conflict', 'identity_ambiguous', 'identity_unresolved',
    'unknown_side', 'unknown_status', 'missing_multiplier', 'invalid_denominator',
    'unknown_currency', 'unknown_basis', 'string_shortened', 'missing_timestamp',
    'calculation_overflow',
]


def parse_decimal(value: object, *, allow_negative: bool = False) -> Decimal | None:
    """Parse source numbers without replacing missing data or accepting nonfinite values."""
    if value is None or isinstance(value, str) and not value.strip():
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError('invalid decimal')
    try:
        result = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValueError('invalid decimal') from exc
    if not result.is_finite():
        raise ValueError('nonfinite decimal')
    if result < 0 and not allow_negative:
        raise ValueError('negative decimal')
    return result


def _signed_decimal(value: object) -> Decimal | None:
    return parse_decimal(value, allow_negative=True)


DecimalValue = Annotated[Decimal | None, BeforeValidator(_signed_decimal)]
NonnegativeDecimal = Annotated[Decimal | None, BeforeValidator(parse_decimal)]


def _risk_decimal_string(value: object) -> str:
    """Validate bounded exact wire strings before constructing decimals."""
    if not isinstance(value,str) or not re.fullmatch(r'-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?',value):
        raise ValueError('expected canonical decimal string')
    if len(value.lstrip('-').replace('.',''))>24 or len(value.partition('.')[2])>8:
        raise ValueError('decimal exceeds 24 digits or 8 fractional places')
    return value


RiskDecimalString = Annotated[str, BeforeValidator(_risk_decimal_string)]


class EvidenceModel(BaseModel):
    model_config = ConfigDict(extra='forbid', validate_assignment=True)


class PortfolioIssue(EvidenceModel):
    code: IssueCode
    row_id: str | None = None
    field: str | None = None


class ValueProvenance(EvidenceModel):
    source: Literal['provider', 'calculated']
    input_paths: list[str] = Field(default_factory=list)
    formula_version: str | None = None
    basis: str | None = None


class RiskInputRecord(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    currency: str | None = None
    basis: str | None = None
    period: str | None = None
    period_start: datetime | None = None
    period_end: datetime | None = None
    source_timestamp: datetime | None = None
    provenance: dict[str, ValueProvenance] = Field(default_factory=dict)


class MarginRiskInput(RiskInputRecord):
    used_margin: RiskDecimalString | None = None
    total_margin: RiskDecimalString | None = None


class PnlRiskInput(RiskInputRecord):
    account_net_pnl: RiskDecimalString | None = None


class RiskInputs(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    margin: MarginRiskInput | None = None
    pnl: PnlRiskInput | None = None


class PortfolioRow(EvidenceModel):
    row_id: str
    underlying_key: str | None = None
    underlying_identity_basis: str | None = None
    inventory_coverage: Literal['disjoint', 'ambiguous'] | None = None
    inventory_coverage_basis: str | None = None

    @model_serializer(mode='wrap')
    def omit_absent_risk_metadata(self, handler):
        data = handler(self)
        for field in ('underlying_key','underlying_identity_basis','inventory_coverage','inventory_coverage_basis'):
            if getattr(self,field) is None:
                data.pop(field,None)
        return data

    exchange: str | None = None
    token: str | None = None
    symbol: str | None = None
    contract_type: str | None = None
    expiry: date | None = None
    strike: NonnegativeDecimal = None
    lot_size: NonnegativeDecimal = None
    currency: Literal['INR'] | None = None
    identity_verified: bool | None = None
    identity_status: Literal['verified', 'unresolved', 'ambiguous', 'invalid'] | None = None
    identity_basis: str | None = None
    quantity: DecimalValue = None
    available_quantity: DecimalValue = None
    buy_quantity: NonnegativeDecimal = None
    sell_quantity: NonnegativeDecimal = None
    filled_quantity: NonnegativeDecimal = None
    pending_quantity: NonnegativeDecimal = None
    average_price: NonnegativeDecimal = None
    last_price: NonnegativeDecimal = None
    order_price: NonnegativeDecimal = None
    trigger_price: NonnegativeDecimal = None
    buy_price: NonnegativeDecimal = None
    sell_price: NonnegativeDecimal = None
    multiplier: NonnegativeDecimal = None
    invested_value: DecimalValue = None
    market_value: DecimalValue = None
    provider_pnl: DecimalValue = None
    calculated_pnl: DecimalValue = None
    realized_pnl: DecimalValue = None
    unrealized_pnl: DecimalValue = None
    pnl_percent: DecimalValue = None
    side: Literal['BUY', 'SELL', 'UNKNOWN'] | None = None
    status: str | None = None
    order_id: str | None = None
    product: str | None = None
    provenance: dict[str, ValueProvenance] = Field(default_factory=dict)
    issues: list[PortfolioIssue] = Field(default_factory=list)


class PortfolioSection(EvidenceModel):
    state: SectionState
    rows: list[PortfolioRow] = Field(default_factory=list)
    values: dict[str, DecimalValue] = Field(default_factory=dict)
    provenance: dict[str, ValueProvenance] = Field(default_factory=dict)
    issues: list[PortfolioIssue] = Field(default_factory=list)
    retrieval_started_at: datetime | None = None
    retrieval_finished_at: datetime | None = None
    provider_timestamp: datetime | None = None
    source_count: int | None = Field(default=None, ge=0)


class PortfolioSnapshot(EvidenceModel):
    risk_inputs: RiskInputs | None = None

    @model_serializer(mode='wrap')
    def omit_absent_risk_inputs(self, handler):
        data = handler(self)
        if self.risk_inputs is None:
            data.pop('risk_inputs',None)
        return data

    schema_version: Literal['portfolio.v1'] = 'portfolio.v1' 
    evidence_id: UUID = Field(default_factory=uuid4)
    source: str = 'kotak'
    retrieval_started_at: datetime
    retrieval_finished_at: datetime
    source_observed_at: datetime
    cache_age_seconds: DecimalValue = Field(default=Decimal('0'), ge=0)
    atomic: Literal[False] = False
    exchange_freshness: Literal['unknown', 'verified'] = 'unknown'
    exchange_timestamp: datetime | None = None
    completeness: Literal['complete', 'partial', 'unavailable', 'invalid'] = 'partial'
    sections: dict[SectionName, PortfolioSection] = Field(default_factory=dict)
    summary: dict[str, DecimalValue] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)


class SectionObservation(BaseModel):
    """Internal transport envelope: never serialize as public evidence."""
    model_config = ConfigDict(extra='forbid', arbitrary_types_allowed=True)
    raw: object | None = None
    retrieval_started_at: datetime | None = None
    retrieval_finished_at: datetime | None = None
    error_code: str | None = None


def serialize_snapshot(snapshot: PortfolioSnapshot) -> str:
    """Canonical key order and exact decimal strings for stable repeated reads."""
    # Revalidate to catch mutable-container changes made after construction.
    validated = PortfolioSnapshot.model_validate(snapshot.model_dump(mode='python'))
    return json.dumps(validated.model_dump(mode='json'), sort_keys=True,
                      separators=(',', ':'), ensure_ascii=False, allow_nan=False)
