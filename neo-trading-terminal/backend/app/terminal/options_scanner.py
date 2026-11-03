"""Bounded deterministic scanner. Ranking is maximum expiry yield, never a risk score."""
from decimal import Decimal, localcontext
from datetime import datetime
from typing import Annotated, Literal
from zoneinfo import ZoneInfo
from pydantic import Field, model_validator
from .options_market_contracts import FrozenContract, MarketDecimal
from .options_strategy_contracts import CostAssumptions, StrategyRequest, calculation_context
from .options_strategies import analyze_strategy

class ScanCriteria(FrozenContract):
    capital_inr: MarketDecimal
    strategy: Literal['covered_call','collar']
    scope: Literal['owned','hypothetical']
    min_expiry_days: Annotated[int,Field(strict=True,ge=1,le=3660)]
    max_expiry_days: Annotated[int,Field(strict=True,ge=1,le=3660)]
    minimum_volume: MarketDecimal
    minimum_open_interest: MarketDecimal
    minimum_depth: MarketDecimal
    maximum_relative_spread: MarketDecimal
    maximum_loss_inr: MarketDecimal
    quote_max_age_seconds: Annotated[int,Field(strict=True,ge=1,le=86400)]
    costs: CostAssumptions

    @model_validator(mode='after')
    def bounded(self):
        if self.capital_inr<=0 or self.max_expiry_days<self.min_expiry_days: raise ValueError('Invalid capital or horizon')
        required=['opening_fees_inr','expiry_fees_inr','stock_slippage_per_unit','call_slippage_per_unit']
        if self.strategy=='collar': required.append('put_slippage_per_unit')
        if any(getattr(self.costs,k) is None for k in required): raise ValueError('Explicit versioned costs required')
        return self

def rank_candidates(candidates):
    """Partition by strategy/horizon/capital basis; exact deterministic ties."""
    with localcontext(calculation_context()):
        return sorted(candidates,key=lambda x:(tuple(x['group']),-Decimal(x['net_horizon_yield']),Decimal(x['relative_spread']),
            -Decimal(x['minimum_volume']),-Decimal(x['minimum_open_interest']),tuple(x['contracts'])))

def scan_evidence(criteria,evidence,holdings,as_of,*,combination_limit=1000):
    criteria=ScanCriteria.model_validate(criteria.model_dump())
    today=as_of.astimezone(ZoneInfo('Asia/Kolkata')).date()
    contracts=sorted(evidence.contracts,key=lambda c:c.instrument_id);quotes={q.contract_id:q for q in evidence.quotes}
    calls=[c for c in contracts if c.kind=='call' and c.expiry and criteria.min_expiry_days<=(c.expiry-today).days<=criteria.max_expiry_days]
    candidates=[];exclusions=[];visited=0;total=0;missing=0;budget_exhausted=False
    with localcontext(calculation_context()):
        for call in calls:
            stocks=[s for s in contracts if s.kind=='equity' and s.identity_verified and s.underlying_id==call.underlying_id]
            puts=[p for p in contracts if p.kind=='put' and p.underlying_id==call.underlying_id and p.expiry==call.expiry and p.strike<=call.strike] if criteria.strategy=='collar' else [None]
            total+=max(1,len(stocks))*max(1,len(puts))
            if not stocks or not puts:
                missing+=max(1,len(stocks))*max(1,len(puts))
                exclusions.append(dict(contracts=[call.instrument_id],reason='required_leg_missing',status='cannot_assess'));continue
            for stock in stocks:
                for put in puts:
                    if visited>=combination_limit: budget_exhausted=True;continue
                    visited+=1;legs=[stock,call]+([put] if put else []);ids=[c.instrument_id for c in legs]
                    reason=None;spreads=[];volumes=[];ois=[]
                    for c in legs:
                        q=quotes.get(c.instrument_id)
                        if q is None: reason='quote_missing';break
                        if any(getattr(q,k) is None for k in ['volume','open_interest','bid_quantity','ask_quantity','bid','ask']): reason='liquidity_missing';break
                        if q.bid<=0 or q.ask<q.bid: reason='quote_invalid';break
                        spread=(q.ask-q.bid)/((q.ask+q.bid)/2)
                        if q.volume<criteria.minimum_volume or q.open_interest<criteria.minimum_open_interest or min(q.bid_quantity,q.ask_quantity)<criteria.minimum_depth: reason='liquidity_threshold';break
                        if spread>criteria.maximum_relative_spread: reason='spread_threshold';break
                        spreads.append(spread);volumes.append(q.volume);ois.append(q.open_interest)
                    holding=next((h for h in holdings if h.stock_contract_id==stock.instrument_id),None)
                    if reason is None and (call.lot_size is None or call.lot_size>1000000): reason='lot_unverified'
                    if reason:
                        exclusions.append(dict(contracts=ids,reason=reason,status='cannot_assess' if reason.endswith(('missing','unverified')) else 'ineligible'));continue
                    # One verified option lot is the reproducible capital unit; no size optimisation.
                    request=StrategyRequest(kind=criteria.strategy,mode=criteria.scope,stock_contract_id=stock.instrument_id,call_contract_id=call.instrument_id,
                        put_contract_id=put.instrument_id if put else None,quantity=call.lot_size,evidence_id=evidence.evidence_id,
                        holding_row_id=holding.row_id if holding and criteria.scope=='owned' else None,costs=criteria.costs,
                        criteria=dict(capital_limit_inr=criteria.capital_inr,maximum_loss_inr=criteria.maximum_loss_inr),quote_max_age_seconds=criteria.quote_max_age_seconds)
                    report=analyze_strategy(request,evidence,holdings,as_of)
                    if report.status!='eligible':
                        exclusions.append(dict(contracts=ids,reason=';'.join(report.reasons),status=report.status));continue
                    candidates.append(dict(group=[criteria.strategy,report.horizon_days,report.capital_basis_label],contracts=ids,
                        net_horizon_yield=str(report.current_basis.horizon_yield),relative_spread=str(max(spreads)),minimum_volume=str(min(volumes)),minimum_open_interest=str(min(ois)),
                        downside_inr=str(report.current_basis.maximum_loss),stock_capital_inr=str(report.stock_capital),broker_margin_inr=None,report=report.model_dump(mode='json')))
    return dict(candidates=rank_candidates(candidates),exclusions=exclusions,visited_combinations=visited,total_combinations=total,missing_combinations=total-visited,partial=total>visited,budget_exhausted=budget_exhausted)
