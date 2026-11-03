"""Public historical schemas. All money is finite decimal text, never JSON floats.

CSV and Parquet share a wide, nullable row table described in examples/options-history.md.
Timestamps are ISO8601 with offsets. Row identities and contract effective versions
are explicit; nothing is inferred from a trading symbol.
"""
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal
from uuid import UUID
from pydantic import AwareDatetime, BeforeValidator, Field, PlainSerializer, model_validator
from .options_market_contracts import FrozenContract, Identifier, Text, decimal_text

MAX_BYTES=10*1024*1024
MAX_ROWS=100000

def exact_money(value):
    if not isinstance(value,(str,Decimal)) or len(str(value))>80:
        raise ValueError('Decimal text required')
    try: result=Decimal(value)
    except InvalidOperation:raise ValueError('Invalid decimal') from None
    if not result.is_finite() or result<0 or result>Decimal('1e18') or result.as_tuple().exponent < -12:
        raise ValueError('Decimal outside bounds')
    return result

Money=Annotated[Decimal,BeforeValidator(exact_money),PlainSerializer(decimal_text,return_type=str,when_used='json')]
PositiveInt=Annotated[int,Field(strict=True,gt=0,le=1000000)]

class ExpectedInterval(FrozenContract):
    contract_id:Identifier
    start:AwareDatetime
    end:AwareDatetime
    interval_seconds:Annotated[int,Field(strict=True,ge=1,le=604800)]
    @model_validator(mode='after')
    def ordered(self):
        if self.start>self.end or (self.end-self.start).total_seconds()/self.interval_seconds>MAX_ROWS:
            raise ValueError('Invalid expected interval')
        return self

class ImportDeclaration(FrozenContract):
    provenance:Text
    licence:Text
    dataset_status:Literal['synthetic','user_import']
    expected_intervals:Annotated[tuple[ExpectedInterval,...],Field(min_length=1,max_length=1000)]

class HistoricalImportBody(ImportDeclaration):
    format:Literal['csv','parquet']='csv'
    csv_text:Annotated[str,Field(max_length=MAX_BYTES)]|None=None
    parquet_base64:Annotated[str,Field(max_length=(MAX_BYTES+2)//3*4)]|None=None
    @model_validator(mode='after')
    def one_source(self):
        if (self.format=='csv' and (self.csv_text is None or self.parquet_base64 is not None)) or (self.format=='parquet' and (self.parquet_base64 is None or self.csv_text is not None)):
            raise ValueError('Exactly one matching payload required')
        return self

class HistoricalCosts(FrozenContract):
    version:Literal['historical-costs.1']='historical-costs.1'
    source:Text
    opening_fee_inr:Money
    expiry_fee_inr:Money
    slippage_per_unit:Money

class HistoricalEntry(FrozenContract):
    decision_at:AwareDatetime
    stock_contract_id:Identifier
    call_contract_id:Identifier
    put_contract_id:Identifier|None=None
    quantity:PositiveInt

class InitialInventory(FrozenContract):
    contract_id:Identifier
    quantity:PositiveInt
    acquisition_cost_per_unit:Money

class BacktestRequest(FrozenContract):
    dataset_id:UUID
    kind:Literal['covered_call','collar']
    mode:Literal['hypothetical','owned']
    entries:Annotated[tuple[HistoricalEntry,...],Field(min_length=1,max_length=100)]
    start:AwareDatetime
    end:AwareDatetime
    initial_capital:Money
    initial_inventory:Annotated[tuple[InitialInventory,...],Field(max_length=100)]=()
    costs:HistoricalCosts
    fill_policy:Literal['depth_required','assume_unlimited_depth']='depth_required'
    quote_max_age_seconds:Annotated[int,Field(strict=True,ge=1,le=86400)]
    valuation_times:Annotated[tuple[AwareDatetime,...],Field(max_length=10000)]=()
    @model_validator(mode='after')
    def ordered(self):
        if self.start>=self.end or self.initial_capital<=0:raise ValueError('Positive capital and ordered range required')
        if self.mode=='hypothetical' and self.initial_inventory:raise ValueError('Hypothetical has no initial inventory')
        if self.mode=='owned' and not self.initial_inventory:raise ValueError('Owned requires explicit initial inventory')
        if len({x.contract_id for x in self.initial_inventory})!=len(self.initial_inventory):raise ValueError('Duplicate inventory')
        if list(self.entries)!=sorted(self.entries,key=lambda x:x.decision_at) or len({x.decision_at for x in self.entries})!=len(self.entries):raise ValueError('Ordered distinct decisions required')
        for e in self.entries:
            ids=[e.stock_contract_id,e.call_contract_id]+([e.put_contract_id] if e.put_contract_id else [])
            if (self.kind=='collar')!=(e.put_contract_id is not None) or len(set(ids))!=len(ids) or not self.start<=e.decision_at<self.end:raise ValueError('Invalid explicit selection')
        if any(not self.start<=t<=self.end for t in self.valuation_times):raise ValueError('Valuation outside range')
        return self
