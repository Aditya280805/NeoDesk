"""Immutable, bounded evidence contracts. Unverified flags are never trading authority."""
from datetime import date
from decimal import Decimal, InvalidOperation
import json
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import (AwareDatetime, BaseModel, BeforeValidator, ConfigDict, Field,
                      PlainSerializer, StrictBool, model_validator)


def market_decimal(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)) or len(str(value)) > 80:
        raise ValueError('Invalid market number')
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise ValueError('Invalid market number') from None
    if not number.is_finite() or number < 0 or number > Decimal('1e18') or number.as_tuple().exponent < -12:
        raise ValueError('Market number outside bounds')
    return number


def decimal_text(value):
    text = format(value, 'f')
    return text.rstrip('0').rstrip('.') if '.' in text else text


MarketDecimal = Annotated[Decimal, BeforeValidator(market_decimal), PlainSerializer(decimal_text, return_type=str, when_used='json')]
Identifier = Annotated[str, Field(min_length=1, max_length=120, pattern=r'^\S(?:.*\S)?$')]
Text = Annotated[str, Field(min_length=1, max_length=500)]
Provenance = Annotated[tuple[Text, ...], Field(min_length=1, max_length=20)]


class FrozenContract(BaseModel):
    model_config = ConfigDict(frozen=True, extra='forbid')


class MarketContract(FrozenContract):
    instrument_id: Identifier
    underlying_id: Identifier | None = None
    exchange: Literal['NSE'] = 'NSE'
    kind: Literal['equity', 'call', 'put']
    expiry: date | None = None
    strike: MarketDecimal | None = None
    lot_size: Annotated[int, Field(strict=True, gt=0, le=1000000)] | None = None
    currency: Literal['INR'] = 'INR'
    identity_verified: StrictBool = False
    settlement_verified: StrictBool = False
    settlement_rule_version: Identifier | None = None
    basis: Text
    provenance: Provenance

    @model_validator(mode='after')
    def consistent(self):
        if self.identity_verified and (self.underlying_id is None or self.lot_size is None):
            raise ValueError('Verified identity requires underlying ID and lot size')
        if self.kind != 'equity' and (self.expiry is None or self.strike is None):
            raise ValueError('Option requires expiry and strike')
        if self.kind == 'equity' and (self.expiry is not None or self.strike is not None):
            raise ValueError('Equity cannot have option terms')
        if self.settlement_verified and (not self.identity_verified or not self.settlement_rule_version):
            raise ValueError('Verified settlement requires verified identity and rule evidence')
        return self


class MarketQuote(FrozenContract):
    contract_id: Identifier
    observed_at: AwareDatetime
    exchange_timestamp: AwareDatetime | None = None
    bid: MarketDecimal | None = None
    ask: MarketDecimal | None = None
    bid_quantity: MarketDecimal | None = None
    ask_quantity: MarketDecimal | None = None
    last: MarketDecimal | None = None
    volume: MarketDecimal | None = None
    open_interest: MarketDecimal | None = None
    iv: MarketDecimal | None = None
    source: Text
    provenance: Provenance

    @model_validator(mode='after')
    def not_crossed(self):
        if self.bid is not None and self.ask is not None and self.bid > self.ask:
            raise ValueError('Crossed quote is unusable')
        if self.iv is not None and self.iv > 10000:
            raise ValueError('IV outside bounds')
        return self


class StrategyMarketEvidence(FrozenContract):
    evidence_id: UUID = Field(default_factory=uuid4)
    observed_at: AwareDatetime
    contracts: Annotated[tuple[MarketContract, ...], Field(max_length=500)] = ()
    quotes: Annotated[tuple[MarketQuote, ...], Field(max_length=500)] = ()
    source: Text
    completeness: Literal['complete', 'partial', 'unavailable']
    limitations: Annotated[tuple[Text, ...], Field(max_length=40)] = ()

    @model_validator(mode='after')
    def identities(self):
        ids = [item.instrument_id for item in self.contracts]
        quote_ids = [item.contract_id for item in self.quotes]
        if len(set(ids)) != len(ids) or len(set(quote_ids)) != len(quote_ids):
            raise ValueError('Duplicate evidence identity')
        if not set(quote_ids).issubset(ids):
            raise ValueError('Quote has no matching contract')
        if self.completeness == 'complete' and (not ids or set(ids) != set(quote_ids)):
            raise ValueError('Incomplete contract quote coverage')
        return self

    def canonical_json(self) -> str:
        data = self.model_dump(mode='json')
        data['contracts'].sort(key=lambda item: item['instrument_id'])
        data['quotes'].sort(key=lambda item: item['contract_id'])
        return json.dumps(data, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)


class CapabilityField(FrozenContract):
    name: Identifier
    status: Literal['supported', 'missing', 'unverified']
    source_reference: Text
    checked_date: date
    adapter_evidence: Text
    official_docs_status: Literal['supported', 'missing', 'unverified'] = 'unverified'


class DataCapabilities(FrozenContract):
    version: Literal['options-data-capabilities.v1'] = 'options-data-capabilities.v1'
    adapter: Text
    adapter_version: Text
    fields: Annotated[tuple[CapabilityField, ...], Field(max_length=100)]

    def status_for(self, name: str) -> str:
        return next((item.status for item in self.fields if item.name == name), 'unverified')
