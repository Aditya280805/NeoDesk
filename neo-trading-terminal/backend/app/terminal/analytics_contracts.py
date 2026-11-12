"""Versioned advisory contracts. No identity or authorization is accepted from models."""
import math
from datetime import date
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator, field_validator
from .options_snapshot import OptionsContext

Role = Literal['options_trading_analysis', 'portfolio_analysis', 'portfolio_risk']


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)


class AnalyticsSnapshotRequest(Contract):
    role: Role
    context: OptionsContext = Field(default_factory=OptionsContext)
    tools: tuple[str, ...] = Field(default=(),max_length=3)
    historical_input: dict[str, Any] | None = None

    @field_validator('historical_input')
    @classmethod
    def valid_history(cls,value):
        if value is not None:
            from .analytics_inputs import HistoricalAnalyticsInput
            return HistoricalAnalyticsInput.model_validate(value).model_dump(mode='json')
        return None

    @model_validator(mode='after')
    def allowed_sections(self):
        from .analytics_runtime import TOOLS_BY_ROLE
        if len(set(self.tools))!=len(self.tools) or not set(self.tools)<=TOOLS_BY_ROLE[self.role]:
            raise ValueError('Analytics sections do not match selected specialist')
        if self.historical_input is not None and OptionsContext.model_validate(self.historical_input['context'])!=self.context:
            raise ValueError('Imported market context differs')
        return self


class RoutingDecision(Contract):
    mode: Literal['SINGLE_OPTIONS', 'SINGLE_PORTFOLIO_ANALYSIS', 'SINGLE_PORTFOLIO_RISK',
                  'COMPOSITE_PIPELINE', 'CLARIFY', 'REJECT_MUTATION_OR_UNSUPPORTED']
    delegated_agents: tuple[Role, ...] = ()
    requested_sections: tuple[str, ...] = Field(default=(), max_length=8)
    extracted_symbol: str | None = Field(default=None, max_length=100)
    extracted_expiry: date | None = None
    reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode='after')
    def valid_stages(self):
        expected = {'SINGLE_OPTIONS': 'options_trading_analysis',
                    'SINGLE_PORTFOLIO_ANALYSIS': 'portfolio_analysis', 'SINGLE_PORTFOLIO_RISK': 'portfolio_risk'}
        if self.mode in expected and self.delegated_agents != (expected[self.mode],):
            raise ValueError('Single route requires matching specialist')
        if self.mode == 'COMPOSITE_PIPELINE':
            order = ('options_trading_analysis', 'portfolio_analysis', 'portfolio_risk')
            if not 2 <= len(self.delegated_agents) <= 3 or tuple(x for x in order if x in self.delegated_agents) != self.delegated_agents:
                raise ValueError('Composite stages must be distinct and dependency ordered')
        if self.mode in ('CLARIFY', 'REJECT_MUTATION_OR_UNSUPPORTED') and self.delegated_agents:
            raise ValueError('Rejected/clarification route cannot delegate')
        return self


class RouterIntent(Contract):
    """Single model classification; trusted code binds modes and ordered roles."""
    route: Literal['OPTIONS','ANALYSIS','RISK','OPTIONS_ANALYSIS','OPTIONS_RISK',
                   'ANALYSIS_RISK','OPTIONS_ANALYSIS_RISK','CLARIFY','REJECT']

    def decision(self):
        roles=tuple(role for domain,role in (('OPTIONS','options_trading_analysis'),('ANALYSIS','portfolio_analysis'),('RISK','portfolio_risk')) if domain in self.route.split('_'))
        singles={'OPTIONS':'SINGLE_OPTIONS','ANALYSIS':'SINGLE_PORTFOLIO_ANALYSIS','RISK':'SINGLE_PORTFOLIO_RISK'}
        mode=singles.get(self.route,'CLARIFY' if self.route=='CLARIFY' else 'REJECT_MUTATION_OR_UNSUPPORTED' if self.route=='REJECT' else 'COMPOSITE_PIPELINE')
        return RoutingDecision(mode=mode,delegated_agents=roles)


class ProposalLeg(Contract):
    contract_id: str = Field(min_length=1, max_length=100)
    underlying_key: str = Field(min_length=1,max_length=100)
    exchange: Literal['nse_fo','bse_fo']
    currency: Literal['INR']
    expiry: date
    side: Literal['BUY', 'SELL']
    quantity: int = Field(strict=True, gt=0, le=1000000)
    lot_size: int = Field(strict=True, gt=0, le=100000)
    strike: Decimal = Field(gt=0, allow_inf_nan=False)
    option_type: Literal['CALL', 'PUT']

    @model_validator(mode='after')
    def lot_multiple(self):
        if self.quantity % self.lot_size:
            raise ValueError('Quantity must be a contract lot multiple')
        return self


class StrategyProposal(Contract):
    schema_version: Literal['strategy-proposal.v1'] = 'strategy-proposal.v1'
    proposal_id: UUID = Field(default_factory=uuid4)
    evidence_id: UUID
    template: Literal['bull_call_spread', 'bear_put_spread']
    valued_at: AwareDatetime
    legs: tuple[ProposalLeg, ...] = Field(min_length=1, max_length=4)

    @model_validator(mode='after')
    def supported_structure(self):
        if len(self.legs)!=2:
            raise ValueError('Debit spread requires two legs')
        buy,sell = self.legs
        if (buy.underlying_key,buy.exchange,buy.currency)!=(sell.underlying_key,sell.exchange,sell.currency):
            raise ValueError('Spread legs must share a canonical underlying, exchange and currency')
        expected_type = 'CALL' if self.template=='bull_call_spread' else 'PUT'
        if (buy.side,sell.side)!=('BUY','SELL') or buy.contract_id==sell.contract_id or buy.expiry!=sell.expiry or buy.quantity!=sell.quantity or buy.lot_size!=sell.lot_size or buy.option_type!=expected_type or sell.option_type!=expected_type:
            raise ValueError('Invalid verified debit spread structure')
        if self.template=='bull_call_spread' and buy.strike>=sell.strike or self.template=='bear_put_spread' and buy.strike<=sell.strike:
            raise ValueError('Invalid debit spread strike ordering')
        return self


class AnalyticsEvidence(Contract):
    schema_version: Literal['analytics-evidence.v1'] = 'analytics-evidence.v1'
    evidence_id: UUID = Field(default_factory=uuid4)
    calculation_version: str
    observed_at: AwareDatetime | None
    retrieved_at: AwareDatetime
    source_refs: tuple[str, ...] = ()
    status: Literal['AVAILABLE', 'PARTIAL', 'UNAVAILABLE']
    metrics: dict[str, Any]
    unavailable_reasons: dict[str, str] = Field(default_factory=dict)
    units: dict[str, str] = Field(default_factory=dict)
    coverage: dict[str, Any] = Field(default_factory=dict)
    limitations: tuple[str, ...] = ()
    candidate_proposals: tuple[StrategyProposal, ...] = ()


def sanitize_quant_payload(value):
    """JSON boundary only: preserve calculation precision and Decimal money."""
    if isinstance(value, dict):
        return {str(k): sanitize_quant_payload(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize_quant_payload(v) for v in value]
    if isinstance(value, Decimal):
        return str(value) if value.is_finite() else None
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if hasattr(value, 'tolist'):
        return sanitize_quant_payload(value.tolist())
    if hasattr(value, 'item'):
        return sanitize_quant_payload(value.item())
    return value
