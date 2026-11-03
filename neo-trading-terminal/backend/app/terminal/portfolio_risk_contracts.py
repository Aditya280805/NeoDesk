"""Strict versioned portfolio policy and risk report contracts."""
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID, uuid4
from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator
from .portfolio_contracts import PortfolioSnapshot, RiskDecimalString
NonnegativeInt = Annotated[int, Field(strict=True, ge=0)]
Outcome = Literal['pass', 'breach', 'cannot_assess']
CheckCode = Literal['concentration', 'expiry', 'margin', 'loss']

class RiskValue(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)

class RiskPolicySettings(RiskValue):
    schema_version: Literal['portfolio-risk-policy.v1'] = 'portfolio-risk-policy.v1'
    concentration_enabled: StrictBool = True
    expiry_enabled: StrictBool = True
    margin_enabled: StrictBool = True
    loss_enabled: StrictBool = True
    concentration_max_percent: RiskDecimalString | None = None
    expiry_window_days: Annotated[int, Field(strict=True, ge=0, le=365)] | None = None
    margin_max_percent: RiskDecimalString | None = None
    loss_max_amount: RiskDecimalString | None = None
    loss_basis: Literal['broker_account_net_pnl'] | None = None
    loss_period: Literal['broker_trading_day'] | None = None
    max_observation_age_seconds: Annotated[int, Field(strict=True, ge=1, le=86400)] | None = None

    @model_validator(mode='after')
    def validate_settings(self):
        for field in ('concentration_max_percent','margin_max_percent','loss_max_amount'):
            value=getattr(self,field)
            if value is not None and Decimal(value)<0:
                raise ValueError('negative policy limit')
        if self.concentration_max_percent is not None and Decimal(self.concentration_max_percent)>100:
            raise ValueError('concentration exceeds 100')
        supplied=[self.loss_max_amount is not None,self.loss_basis is not None,self.loss_period is not None]
        if any(supplied) and not all(supplied):
            raise ValueError('loss amount, basis and period must be configured together')
        return self

class RiskPolicy(RiskPolicySettings):
    revision: NonnegativeInt

class RiskPolicyUpdate(RiskValue):
    expected_revision: NonnegativeInt
    policy: RiskPolicySettings

class RiskFinding(RiskValue):
    code: CheckCode
    enabled: StrictBool
    outcome: Outcome
    scope: str | None = None
    measured: RiskDecimalString | None = None
    limit: RiskDecimalString | None = None
    unit: str | None = None
    numerator: RiskDecimalString | None = None
    denominator: RiskDecimalString | None = None
    affected_row_ids: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)

class RiskCoverage(RiskValue):
    passed: NonnegativeInt
    breached: NonnegativeInt
    cannot_assess: NonnegativeInt
    disabled: NonnegativeInt
    @property
    def enabled(self):
        return self.passed+self.breached+self.cannot_assess
    @property
    def assessed(self):
        return self.passed+self.breached

class RiskObservationTimes(RiskValue):
    retrieval_started_at: datetime | None = None
    retrieval_finished_at: datetime | None = None
    source_timestamp: datetime | None = None

class RiskReport(RiskValue):
    schema_version: Literal['portfolio-risk.v1'] = 'portfolio-risk.v1'
    report_id: UUID = Field(default_factory=uuid4)
    evidence_id: UUID
    policy_revision: NonnegativeInt
    calculation_version: Literal['portfolio-risk.1'] = 'portfolio-risk.1'
    evaluated_at: datetime
    observation_times: dict[str,RiskObservationTimes] = Field(default_factory=dict)
    summary: Outcome
    coverage: RiskCoverage
    limitations: list[str] = Field(default_factory=list)
    findings: list[RiskFinding] = Field(min_length=4,max_length=4)
    @model_validator(mode='after')
    def unique_checks(self):
        if {f.code for f in self.findings}!={'concentration','expiry','margin','loss'}:
            raise ValueError('requires each risk check exactly once')
        return self

class PortfolioRiskEnvelope(PortfolioSnapshot):
    risk_report: RiskReport
    @model_validator(mode='after')
    def matching_evidence(self):
        if self.evidence_id!=self.risk_report.evidence_id:
            raise ValueError('report evidence does not match snapshot')
        return self
