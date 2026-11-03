"""Versioned platform policy and pure exact risk arithmetic; no account-equity inference."""
from datetime import datetime
from decimal import Decimal, localcontext
from typing import Annotated, Literal
from uuid import UUID, uuid4
from pydantic import AwareDatetime, Field, StrictBool
from .options_market_contracts import FrozenContract, MarketDecimal
from .options_strategy_contracts import ExactDecimal, calculation_context

class PlatformRiskPolicy(FrozenContract):
    version: Literal['platform-risk.v1']='platform-risk.v1'
    revision: Annotated[int,Field(strict=True,ge=0)]=0
    capital_cap_inr: MarketDecimal|None=None
    underlying_exposure_maxpercent: Annotated[MarketDecimal,Field(le=100)]|None=None
    strategy_maxloss_inr: MarketDecimal|None=None
    drawdown_maxpercent: Annotated[MarketDecimal,Field(le=100)]|None=None
    observation_max_age_seconds: Annotated[int,Field(strict=True,ge=1,le=86400)]|None=None

class MonitoringSettings(FrozenContract):
    enabled: StrictBool=False
    interval_seconds: Annotated[int,Field(strict=True,ge=60,le=86400)]=60

class EquityObservation(FrozenContract):
    observation_id: UUID=Field(default_factory=uuid4)
    observed_at: AwareDatetime
    sequence: Annotated[int,Field(strict=True,ge=0)]
    equity_inr: MarketDecimal
    external_flow_inr: ExactDecimal=Decimal(0)
    flow_timing: Literal['before_valuation_at_prior_nav','unknown']='before_valuation_at_prior_nav'
    currency: Literal['INR']='INR'
    complete: StrictBool=True
    source: Literal['user_declared']='user_declared'

class EquityImport(FrozenContract):
    observations: Annotated[tuple[EquityObservation,...],Field(min_length=1,max_length=500)]

class AssociationRequest(FrozenContract):
    portfolio_evidence_id: UUID
    row_ids: Annotated[tuple[str,...],Field(min_length=1,max_length=20)]
    fill_ids: Annotated[tuple[str,...],Field(max_length=100)]=()
    confirm_executed: StrictBool=False
    costs_inr: MarketDecimal|None=None
    costs_source: Literal['user_declared']='user_declared'
    lot_ledger_id: UUID|None=None

def unitized_drawdown(observations):
    """External flows issue/redeem units at prior NAV, before next valuation.

    Sequence zero anchors a declared complete series. Gaps, unknown flow timing,
    nonpositive unit/equity denominators and conflicting chronology fail closed.
    Returns maximum percentage drawdown over the supplied complete series.
    """
    rows=tuple(EquityObservation.model_validate(x.model_dump() if isinstance(x,EquityObservation) else x) for x in observations)
    if len(rows)<2 or rows[0].sequence!=0 or rows[0].external_flow_inr!=0: return None
    with localcontext(calculation_context()):
        first=rows[0]
        if first.equity_inr<=0: return None
        units=first.equity_inr; nav=peak=Decimal(1); result=Decimal(0)
        for i,row in enumerate(rows):
            if not row.complete or row.sequence!=i or row.flow_timing!='before_valuation_at_prior_nav': return None
            if i==0: continue
            if row.observed_at<=rows[i-1].observed_at: return None
            if nav<=0: return None
            units+=row.external_flow_inr/nav
            if units<=0 or row.equity_inr<=0: return None
            nav=row.equity_inr/units;peak=max(peak,nav)
            result=max(result,(peak-nav)/peak*100)
        return result

def evaluate_platform_risk(policy, snapshot, reports=(), associations=(), equity=(), *, as_of:datetime):
    """Snapshot is validated server evidence. Exposure never substitutes option premium."""
    from .portfolio_contracts import PortfolioSnapshot
    policy=PlatformRiskPolicy.model_validate(policy.model_dump())
    snapshot=PortfolioSnapshot.model_validate(snapshot.model_dump() if isinstance(snapshot,PortfolioSnapshot) else snapshot)
    checks=[]
    with localcontext(calculation_context()):
        def check(key,limit,value,reason,refs=()):
            checks.append(dict(key=key,outcome='cannot_assess' if limit is None or value is None else 'breach' if value>limit else 'pass',
                limit=None if limit is None else str(limit),value=None if value is None else str(value),reason=reason,
                evidence_ids=[str(snapshot.evidence_id)],report_ids=list(map(str,refs))))
        age=Decimal(str((as_of-snapshot.source_observed_at).total_seconds()))
        fresh=age>=0 and (policy.observation_max_age_seconds is None or age<=policy.observation_max_age_seconds)
        check('observation_age',policy.observation_max_age_seconds,age if age>=0 else None,'server snapshot age')
        # Only confirmed fills with compatible CURRENT inventory may enter account
        # sizing. An explicit saved hypothetical association alone is not execution.
        expected={str(a['baseline_analysis_id']) for a in associations if a.get('executed_confirmed') is True}
        covered={id for id in expected if all(a.get('current_coverage_verified') is True for a in associations
                 if str(a['baseline_analysis_id'])==id and a.get('executed_confirmed') is True)}
        by_id={str(r.report_id):r for r in reports}
        selected=[by_id[id] for id in sorted(expected) if id in by_id]
        # Complete explicit association coverage is required; hypothetical reports
        # cannot silently become account positions.
        capital=sum((r.current_capital for r in selected),Decimal(0)) if expected and expected<=covered and expected<=by_id.keys() and fresh and all(r.current_capital is not None for r in selected) else None
        check('capital',policy.capital_cap_inr,capital,'explicit associated strategy capital; missing coverage remains unavailable',[r.report_id for r in selected])
        for id in sorted(expected):
            r=by_id.get(id)
            check('strategy_loss:'+id,policy.strategy_maxloss_inr,r.current_basis.maximum_loss if fresh and id in covered and r and r.current_basis else None,'expiry model maximum loss; complete compatible association required',[id])
        if not expected: check('strategy_loss',policy.strategy_maxloss_inr,None,'no explicit associated strategies')
        check('underlying_exposure',policy.underlying_exposure_maxpercent,None,'compatible account-wide delta exposure and equity unavailable; premium is not exposure')
        equity=tuple(EquityObservation.model_validate(x.model_dump() if isinstance(x,EquityObservation) else x) for x in equity)
        equity_fresh=bool(equity) and all(x.observed_at<=as_of for x in equity)
        if equity_fresh and policy.observation_max_age_seconds is not None:
            equity_fresh=(as_of-equity[-1].observed_at).total_seconds()<=policy.observation_max_age_seconds
        dd=unitized_drawdown(equity) if equity_fresh else None
        check('drawdown',policy.drawdown_maxpercent,dd,'unitized complete user-declared equity series; external flows at prior NAV')
    return dict(report_id=str(uuid4()),version='platform-risk-calculation.1',policy_revision=policy.revision,
        evaluated_at=as_of.isoformat(),checks=checks,equity_source='user_declared',coverage='explicit_associations_only')
