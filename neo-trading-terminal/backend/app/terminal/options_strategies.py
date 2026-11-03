"""Pure, isolated Decimal expiration payoff; no providers, persistence or orders."""
from datetime import datetime
from dataclasses import dataclass
from decimal import Decimal, localcontext
from types import MappingProxyType
from typing import Literal
from zoneinfo import ZoneInfo
from .options_market_contracts import StrategyMarketEvidence
from .options_strategy_contracts import (StrategyRequest, StrategyReport, HoldingEvidence,
    StrategyCosts, PayoffMetrics, Scenario, calculation_context)

ZERO=Decimal(0)

@dataclass(frozen=True)
class SettlementRule:
    """Server-owned semantics; opaque identifiers never encode these fields."""
    version: str
    exercise_style: Literal['european','american']
    settlement_style: Literal['physical','cash']
    applicability: Literal['synthetic_fixture_only','verified_nse_optstk']
    source_reference: str
    required_evidence_source: str
    required_contract_provenance: str

# No live exchange rule has been certified by Task1. This exact entry supplies
# mathematical test semantics only; it makes no claim about NSE applicability.
SETTLEMENT_RULES=MappingProxyType({
    'nse-optstk-physical-2019.v1':SettlementRule(
        version='nse-optstk-physical-2019.v1',exercise_style='european',settlement_style='physical',
        applicability='verified_nse_optstk',
        source_reference='https://www.nseindia.in/static/products-services/equity-derivatives-individual-securities ; https://www.sebi.gov.in/sebi_data/attachdocs/dec-2018/1546255335099.pdf ; https://archives.nseindia.com/content/circulars/INSP47293.pdf',
        required_evidence_source='kotak-scanner',
        required_contract_provenance='verified current NSE OPTSTK identity, lot and corporate-action deliverable'),
    'fixture-rule-001':SettlementRule(
        version='fixture-rule-001',exercise_style='european',settlement_style='physical',
        applicability='synthetic_fixture_only',
        source_reference='backend/tests/test_options_strategies.py:fixture; synthetic mathematical test definition',
        required_evidence_source='fixture',
        required_contract_provenance='synthetic fixture settlement rule; not exchange certification'),
})

def _settlement_rule(contract,evidence):
    rule=SETTLEMENT_RULES.get(contract.settlement_rule_version)
    if (not contract.settlement_verified or rule is None or rule.version!=contract.settlement_rule_version
        or rule.exercise_style!='european' or rule.settlement_style!='physical'
        or rule.applicability not in ('synthetic_fixture_only','verified_nse_optstk')
        or evidence.source!=rule.required_evidence_source
        or rule.required_contract_provenance not in contract.provenance):
        return None
    if rule.applicability=='verified_nse_optstk' and (contract.exchange!='NSE' or contract.kind not in ('call','put')
        or not contract.identity_verified or 'kotak-scrip-master:pInstType=OPTSTK' not in contract.provenance):
        return None
    return rule

def _metrics(q,basis,kc,call,kp,put,cost,capital,label):
    def profit(s): return q*(s-basis+call-max(s-kc,ZERO)+(max(kp-s,ZERO)-put if kp is not None else ZERO))-cost
    knots=sorted({ZERO,kc}|({kp} if kp is not None else set()))
    values=[profit(s) for s in knots]
    roots={s for s,v in zip(knots,values) if v==0}
    for a,b in zip(knots,knots[1:]):
        pa,pb=profit(a),profit(b)
        if pa*pb<0: roots.add(a-pa*(b-a)/(pb-pa))
    regions=[]
    for a,b in zip(knots,knots[1:]):
        if profit(a)==0 and profit(b)==0:
            if regions and regions[-1][1]==a: regions[-1]=(regions[-1][0],b)
            else: regions.append((a,b))
    if values[-1]==0:
        if regions and regions[-1][1]==knots[-1]: regions[-1]=(regions[-1][0],None)
        else: regions.append((knots[-1],None))
    # Beyond final strike the covered payoff is flat; its endpoint is already included.
    return PayoffMetrics(basis_label=label,stock_basis=basis,quantity=q,call_strike=kc,call_premium=call,
        put_strike=kp,put_premium=put,total_costs=cost,max_profit=max(values),min_profit=min(values),
        maximum_loss=max(ZERO,-min(values)),breakevens=tuple(sorted(roots)),zero_profit_regions=tuple(regions),
        horizon_yield=max(values)/capital if capital is not None and capital>0 else None)

def analyze_strategy(request: StrategyRequest,evidence: StrategyMarketEvidence,
                     holdings: tuple[HoldingEvidence,...]|None,as_of: datetime)->StrategyReport:
    """Selections must reference server-owned evidence; callers own that trust boundary.

    Eligible means all requested analytical gates pass, never permission to trade.
    Horizon yield is maximum expiry net profit/current capital (fraction, unannualized).
    """
    request=StrategyRequest.model_validate(request.model_dump())
    evidence=StrategyMarketEvidence.model_validate(evidence.model_dump())
    if as_of.tzinfo is None or as_of.utcoffset() is None: raise ValueError('Aware evaluation time required')
    with localcontext(calculation_context()):
        return _analyze(request,evidence,holdings,as_of)

def _analyze(r,e,holdings,now):
    reasons=[]; breaches=[]; limitations=list(e.limitations)+[
        'Expiration model excludes early liquidation, dividends, corporate actions, assignment funding and tax effects.',
        'Fee and slippage assumptions are user-supplied, not broker verified. Broker margin is unknown.',
        'Horizon yield is maximum expiry net profit divided by current capital; no annualization.',
        'Analytical eligibility does not reserve collateral or guarantee executable fills.']
    if r.evidence_id!=e.evidence_id: reasons.append('evidence_mismatch')
    age=(now-e.observed_at).total_seconds()
    if age<0 or age>r.quote_max_age_seconds: reasons.append('evidence_time_invalid')
    by_id={x.instrument_id:x for x in e.contracts}; quotes={x.contract_id:x for x in e.quotes}
    ids=[r.stock_contract_id,r.call_contract_id]+([r.put_contract_id] if r.put_contract_id else [])
    legs=tuple(by_id[id] for id in ids if id in by_id)
    if len(legs)!=len(ids): reasons.append('contract_missing')
    expiry=None;horizon=None;basis=None;call=None;put=ZERO;acquisition=None;holding_id=None
    kc=kp=None;used_holdings=()
    if len(legs)==len(ids):
        stock,c=legs[:2];p=legs[2] if len(legs)==3 else None
        expiry=c.expiry; horizon=(expiry-now.astimezone(ZoneInfo('Asia/Kolkata')).date()).days if expiry is not None else None
        if horizon is not None and horizon<=0: breaches.append('expiry_not_future')
        if stock.kind!='equity' or c.kind!='call' or (p and p.kind!='put'): breaches.append('leg_type_invalid')
        if not all(x.identity_verified for x in legs) or not stock.underlying_id or any(x.underlying_id!=stock.underlying_id for x in legs): reasons.append('underlying_unverified')
        if not all(x.exchange=='NSE' and x.currency=='INR' for x in legs): breaches.append('unsupported_market')
        if any(x.lot_size is None for x in legs): reasons.append('lot_unverified')
        elif any(r.quantity%x.lot_size for x in legs): breaches.append('lot_multiple')
        settlement_rules=tuple(_settlement_rule(x,e) for x in legs[1:])
        if any(rule is None for rule in settlement_rules): reasons.append('settlement_unverified')
        if any(rule is not None and rule.applicability=='synthetic_fixture_only' for rule in settlement_rules):
            limitations.append('Settlement semantics use a synthetic fixture rule, not exchange certification or verified NSE applicability.')
        if p and p.expiry!=expiry: breaches.append('expiry_mismatch')
        kc=c.strike;kp=p.strike if p else None
        if kp is not None and kc is not None and kp>kc: breaches.append('put_above_call')
        for id in ids:
            quote=quotes.get(id)
            if quote is None: reasons.append('quote_missing');continue
            age=(now-quote.observed_at).total_seconds()
            if age<0: reasons.append('quote_future')
            elif age>r.quote_max_age_seconds: reasons.append('quote_stale')
            if quote.exchange_timestamp is None: reasons.append('exchange_time_unverified')
            elif not 0<=(now-quote.exchange_timestamp).total_seconds()<=r.quote_max_age_seconds: reasons.append('exchange_time_invalid')
        sq,cq,pq=quotes.get(stock.instrument_id),quotes.get(c.instrument_id),quotes.get(p.instrument_id) if p else None
        if sq:
            basis=sq.ask if r.mode=='hypothetical' else (sq.bid if sq.bid is not None else sq.last)
            if r.mode=='owned' and sq.bid is None and sq.last is not None:
                limitations.append('Owned current valuation uses last price only, never an executable quote.')
                reasons.append('owned_last_only')
        call=cq.bid if cq else None
        put=pq.ask if pq else None if p else ZERO
        if basis is None or call is None or put is None: reasons.append('quote_missing')
        for quote,side in [(sq,'ask' if r.mode=='hypothetical' else 'bid'),(cq,'bid')]+([(pq,'ask')] if p else []):
            size=getattr(quote,side+'_quantity') if quote else None
            if size is None: reasons.append('quote_size_unverified')
            elif size<r.quantity: breaches.append('quote_size_shortfall')
        if r.mode=='owned':
            rows=tuple(HoldingEvidence.model_validate(h.model_dump()) for h in (holdings or ()))
            found=[h for h in rows if h.row_id==r.holding_row_id]
            if len(found)!=1: reasons.append('holding_missing')
            else:
                h=found[0];holding_id=h.evidence_id;used_holdings=(h,)
                if not h.identity_verified or not h.coverage_verified or h.stock_contract_id!=stock.instrument_id or h.underlying_id!=stock.underlying_id: reasons.append('holding_coverage_unverified')
                if not 0<=(now-h.observed_at).total_seconds()<=r.quote_max_age_seconds: reasons.append('holding_stale')
                if h.available_quantity is None: reasons.append('holding_quantity_missing')
                elif h.available_quantity<r.quantity: breaches.append('holding_shortfall')
                acquisition=h.acquisition_cost_per_share
            if acquisition is None and r.acquisition_cost_per_share is not None:
                acquisition=r.acquisition_cost_per_share
                limitations.append('Acquisition basis is a user estimate; it does not modify broker holdings.')
            elif acquisition is not None and r.acquisition_cost_per_share is not None:
                limitations.append('Broker holding acquisition basis takes precedence over the user estimate.')
    costs=r.costs
    required=[costs.opening_fees_inr,costs.expiry_fees_inr,costs.stock_slippage_per_unit,costs.call_slippage_per_unit]
    if r.kind=='collar': required.append(costs.put_slippage_per_unit)
    total=None;slippage=None
    if any(v is None for v in required): reasons.append('costs_missing')
    else:
        slippage=r.quantity*(costs.stock_slippage_per_unit+costs.call_slippage_per_unit+(costs.put_slippage_per_unit if r.kind=='collar' else ZERO))
        total=costs.opening_fees_inr+costs.expiry_fees_inr+slippage
    gross=net=acq=None;stockcapital=capital=None;scenarios=();cashflows={}
    if all(v is not None for v in (basis,call,put,kc)) and (r.kind!='collar' or kp is not None):
        stockcapital=r.quantity*basis
        capital=stockcapital+r.quantity*(put-call)+(costs.opening_fees_inr+slippage if total is not None else ZERO)
        if total is None: capital=None
        elif capital<=0: breaches.append('nonpositive_capital')
        gross=_metrics(r.quantity,basis,kc,call,kp,put,ZERO,None,'current stock valuation; gross expiration payoff')
        if total is not None:
            net=_metrics(r.quantity,basis,kc,call,kp,put,total,capital,'current stock valuation; net expiration payoff')
            if acquisition is not None: acq=_metrics(r.quantity,acquisition,kc,call,kp,put,total,None,'acquisition stock cost; net expiration payoff')
        prices=sorted({ZERO,basis,kc,kc*2}|({kp} if kp is not None else set()))
        scenarios=tuple(Scenario(underlying_price=s,gross_profit=gross.profit_at(s),current_basis_net_profit=net.profit_at(s) if net else None,acquisition_basis_net_profit=acq.profit_at(s) if acq else None) for s in prices)
        cashflows={'call_premium_received_inr':r.quantity*call,'put_premium_paid_inr':r.quantity*put,
            'stock_purchase_inr':stockcapital if r.mode=='hypothetical' else ZERO,
            'opening_fees_inr':costs.opening_fees_inr,'expiry_fees_inr':costs.expiry_fees_inr}
    criteria=r.criteria
    if criteria.require_broker_margin: reasons.append('broker_margin_unavailable')
    if criteria.capital_limit_inr is not None:
        if capital is None: reasons.append('capital_unavailable')
        elif capital>criteria.capital_limit_inr: breaches.append('capital_limit')
    if criteria.maximum_loss_inr is not None:
        if net is None: reasons.append('maximum_loss_unavailable')
        elif net.maximum_loss>criteria.maximum_loss_inr: breaches.append('maximum_loss_limit')
    return StrategyReport(evidence_ids=(e.evidence_id,)+((holding_id,) if holding_id else ()),evaluated_at=now,request=r,
        status='ineligible' if breaches else 'cannot_assess' if reasons else 'eligible',reasons=tuple(dict.fromkeys(breaches+reasons)),
        selected_legs=legs,holding_evidence=used_holdings,quantity=r.quantity,expiry=expiry,horizon_days=horizon,cashflows=cashflows,
        costs=StrategyCosts(opening_inr=costs.opening_fees_inr,expiry_inr=costs.expiry_fees_inr,slippage_inr=slippage,total_inr=total),
        stock_capital=stockcapital,current_capital=capital,gross_current_basis=gross,current_basis=net,acquisition_basis=acq,
        scenarios=scenarios,limitations=tuple(limitations))
