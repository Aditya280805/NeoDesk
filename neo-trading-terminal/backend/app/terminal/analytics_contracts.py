"""Versioned advisory contracts. No identity or authorization is accepted from models."""
import math
from datetime import date
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

Role = Literal['options_trading_analysis', 'portfolio_analysis', 'portfolio_risk']


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)


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


class ProposalLeg(Contract):
    contract_id: str = Field(min_length=1, max_length=100)
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
    template: Literal['bull_call_spread', 'bear_put_spread', 'iron_condor', 'covered_call']
    valued_at: AwareDatetime
    legs: tuple[ProposalLeg, ...] = Field(min_length=1, max_length=4)


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
