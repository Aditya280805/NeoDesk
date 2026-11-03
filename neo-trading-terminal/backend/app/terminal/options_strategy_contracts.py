"""Immutable selections and exact expiration analysis. Public selections carry no truth flags."""
from datetime import date
from decimal import Decimal, localcontext, Context, ROUND_HALF_EVEN, InvalidOperation, DivisionByZero, Overflow
from typing import Annotated, Literal
from uuid import UUID, uuid4
from pydantic import AwareDatetime, BeforeValidator, Field, PlainSerializer, StrictBool, model_validator
from .options_market_contracts import FrozenContract, Identifier, MarketDecimal, MarketContract, decimal_text

def signed_decimal(value):
    if isinstance(value,bool) or not isinstance(value,(str,int,float,Decimal)) or len(str(value))>200:
        raise ValueError('Invalid decimal')
    result=Decimal(str(value))
    if not result.is_finite() or result.copy_abs()>Decimal('1e40') or result.as_tuple().exponent < -160:
        raise ValueError('Decimal outside bounds')
    return result

ExactDecimal=Annotated[Decimal,BeforeValidator(signed_decimal),PlainSerializer(decimal_text,return_type=str,when_used='json')]

def calculation_context():
    return Context(prec=80,rounding=ROUND_HALF_EVEN,Emin=-999999,Emax=999999,
        capitals=1,clamp=0,flags=[],traps=[InvalidOperation,DivisionByZero,Overflow])

class CostAssumptions(FrozenContract):
    version: Literal['strategy-costs.v1']='strategy-costs.v1'
    source: Literal['user-supplied']='user-supplied'
    opening_fees_inr: MarketDecimal|None=None
    expiry_fees_inr: MarketDecimal|None=None
    stock_slippage_per_unit: MarketDecimal|None=None
    call_slippage_per_unit: MarketDecimal|None=None
    put_slippage_per_unit: MarketDecimal|None=None

class StrategyCriteria(FrozenContract):
    capital_limit_inr: MarketDecimal|None=None
    maximum_loss_inr: MarketDecimal|None=None
    require_broker_margin: StrictBool=False

class StrategyRequest(FrozenContract):
    kind: Literal['covered_call','collar']
    mode: Literal['owned','hypothetical']
    stock_contract_id: Identifier
    call_contract_id: Identifier
    put_contract_id: Identifier|None=None
    quantity: Annotated[int,Field(strict=True,gt=0,le=1000000)]
    evidence_id: UUID
    holding_row_id: Identifier|None=None
    acquisition_cost_per_share: MarketDecimal|None=None
    costs: CostAssumptions=Field(default_factory=CostAssumptions)
    criteria: StrategyCriteria=Field(default_factory=StrategyCriteria)
    quote_max_age_seconds: Annotated[int,Field(strict=True,ge=1,le=86400)]

    @model_validator(mode='after')
    def legs(self):
        if (self.kind=='collar') != (self.put_contract_id is not None):
            raise ValueError('Only collar requires a put')
        ids=[self.stock_contract_id,self.call_contract_id]+([self.put_contract_id] if self.put_contract_id else [])
        if len(set(ids))!=len(ids): raise ValueError('Legs must be distinct')
        if self.mode=='hypothetical' and self.holding_row_id is not None: raise ValueError('Hypothetical has no holding row')
        return self

class HoldingEvidence(FrozenContract):
    """Internal server adapter result; never accepted by a public route."""
    row_id: Identifier
    stock_contract_id: Identifier
    underlying_id: Identifier|None=None
    available_quantity: MarketDecimal|None=None
    acquisition_cost_per_share: MarketDecimal|None=None
    observed_at: AwareDatetime
    evidence_id: UUID
    identity_verified: StrictBool=False
    coverage_verified: StrictBool=False

class StrategyCosts(FrozenContract):
    opening_inr: ExactDecimal|None=None
    expiry_inr: ExactDecimal|None=None
    slippage_inr: ExactDecimal|None=None
    total_inr: ExactDecimal|None=None
    source: Literal['user-supplied']='user-supplied'

class PayoffMetrics(FrozenContract):
    basis_label: str
    stock_basis: ExactDecimal
    quantity: int
    call_strike: ExactDecimal
    call_premium: ExactDecimal
    put_strike: ExactDecimal|None=None
    put_premium: ExactDecimal=Decimal(0)
    total_costs: ExactDecimal
    max_profit: ExactDecimal
    min_profit: ExactDecimal
    maximum_loss: ExactDecimal
    breakevens: tuple[ExactDecimal,...]=()
    # Closed intervals; null upper endpoint denotes an unbounded ray.
    # breakevens retains boundary points for compatibility.
    zero_profit_regions: tuple[tuple[ExactDecimal,ExactDecimal|None],...]=()
    horizon_yield: ExactDecimal|None=None

    def profit_at(self,price: Decimal)->Decimal:
        price=signed_decimal(price)
        if price<0: raise ValueError('Underlying price must be nonnegative')
        with localcontext(calculation_context()):
            return self.quantity*(price-self.stock_basis+self.call_premium-max(price-self.call_strike,Decimal(0))+
                (max(self.put_strike-price,Decimal(0))-self.put_premium if self.put_strike is not None else 0))-self.total_costs

class Scenario(FrozenContract):
    underlying_price: ExactDecimal
    gross_profit: ExactDecimal
    current_basis_net_profit: ExactDecimal|None=None
    acquisition_basis_net_profit: ExactDecimal|None=None

class StrategyReport(FrozenContract):
    report_id: UUID=Field(default_factory=uuid4)
    evidence_ids: tuple[UUID,...]
    calculation_version: Literal['options-strategy.1']='options-strategy.1'
    evaluated_at: AwareDatetime
    request: StrategyRequest
    status: Literal['eligible','ineligible','cannot_assess']
    analysis_label: Literal['theoretical','executable']='theoretical'
    reasons: tuple[str,...]=()
    selected_legs: tuple[MarketContract,...]=()
    holding_evidence: tuple[HoldingEvidence,...]=()
    quantity: int
    expiry: date|None=None
    horizon_days: int|None=None
    cashflows: dict[str,ExactDecimal|None]=Field(default_factory=dict)
    costs: StrategyCosts=Field(default_factory=StrategyCosts)
    stock_capital: ExactDecimal|None=None
    current_capital: ExactDecimal|None=None
    capital_basis_label: str='current stock valuation plus put premium minus call premium plus opening fees and slippage'
    broker_margin: ExactDecimal|None=None
    gross_current_basis: PayoffMetrics|None=None
    current_basis: PayoffMetrics|None=None
    acquisition_basis: PayoffMetrics|None=None
    scenarios: tuple[Scenario,...]=()
    limitations: tuple[str,...]=()

class BaselineRequest(FrozenContract):
    analysis_id: UUID
    name: Annotated[str,Field(min_length=1,max_length=100)]

class StrategyBaseline(BaselineRequest):
    baseline_id: UUID=Field(default_factory=uuid4)
    created_at: AwareDatetime
    calculation_version: str
    evidence_ids: tuple[UUID,...]
