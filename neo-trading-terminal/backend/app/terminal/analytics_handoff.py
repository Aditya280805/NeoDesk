"""Server-resolved advisory proposals, carried inside existing role payloads."""
from uuid import UUID, NAMESPACE_URL, uuid5

from .analytics_capture import CapturedAnalytics
from .analytics_contracts import AnalyticsEvidence, StrategyProposal
from .analytics_runtime import TOOLS_BY_ROLE
from .quant_proposals import spread_payoff
from .indian_charges import declared_fee_estimate
from decimal import Decimal
from zoneinfo import ZoneInfo
from .quant_risk import stress_matrix,historical_repricing
from .options_snapshot import OptionsContext


def resolve_selection(captured, result):
    selected = result.get('selected_proposal_id')
    if selected is None:
        return None
    if result['role'] != 'options_trading_analysis':
        raise ValueError('Only options may originate a strategy proposal')
    original = captured.for_role('options_trading_analysis')
    candidates = []
    for name, payload in result.get('evidence', {}).items():
        item = AnalyticsEvidence.model_validate(payload)
        if name not in original or item != original[name]:
            raise ValueError('Selection must cite unchanged consumed options evidence')
        candidates.extend(item.candidate_proposals)
    matches = [proposal for proposal in candidates if proposal.proposal_id == UUID(str(selected))]
    if len(matches) != 1:
        raise ValueError('Selected proposal is not uniquely bound to consumed evidence')
    return matches[0]


def project_proposal(captured, proposal, role,*,quant_inputs=None,valuation_time=None):
    proposal = StrategyProposal.model_validate(proposal)
    if role not in ('portfolio_analysis','portfolio_risk'):
        raise ValueError('Invalid downstream proposal role')
    source = next((item for item in captured.for_role('options_trading_analysis').values()
        if item.evidence_id==proposal.evidence_id and proposal in item.candidate_proposals),None)
    if source is None:
        raise ValueError('Proposal is outside captured options evidence')
    depth = source.metrics.get('broker_quote_depth',{})
    quote_map = {quote['contract_id']:quote for quote in depth.get('quotes',[])}
    gross = entry_fees = None
    bound_cost = None
    if all(leg.contract_id in quote_map and quote_map[leg.contract_id].get('bid') is not None and quote_map[leg.contract_id].get('ask') is not None for leg in proposal.legs):
        gross = spread_payoff(proposal,quote_map)
        transactions = []
        for leg in proposal.legs:
            price = Decimal(quote_map[leg.contract_id]['ask' if leg.side=='BUY' else 'bid'])
            if price*leg.quantity*100>9007199254740991:
                raise ValueError('Entry turnover exceeds exact browser paise range')
            transactions.append(dict(transaction_id=leg.contract_id,product='option',side=leg.side,
                turnover_inr=str(price*leg.quantity),turnover_basis='option_premium',
                trade_date=proposal.valued_at.astimezone(ZoneInfo('Asia/Kolkata')).date().isoformat(),
                cost_source='captured_bid_ask_entry_scenario; broker/exchange/slippage inputs unavailable'))
        entry_fees = declared_fee_estimate(transactions)
        for scenario in (quant_inputs or {}).get('proposal_cost_scenarios',[]):
            buy,sell = proposal.legs
            if (scenario['template'],scenario['buy_contract_id'],scenario['sell_contract_id'],scenario['expiry'],scenario['quantity'])!=(proposal.template,buy.contract_id,sell.contract_id,buy.expiry,buy.quantity):
                continue
            if abs((scenario['valued_at']-proposal.valued_at).total_seconds())>10:
                continue
            if any(Decimal(quote_map[leg.contract_id][side])!=scenario[f'{label}_{side}'] for label,leg in (('buy',buy),('sell',sell)) for side in ('bid','ask')):
                continue
            if bound_cost is not None:
                raise ValueError('Ambiguous matching proposal cost scenarios')
            known_entry = sum(value for transaction in entry_fees['transactions'] for key,value in transaction['charges'].items() if key.endswith('_paise') and key!='total_paise' and value is not None)
            if scenario['roundtrip_cost_paise']<known_entry:
                raise ValueError('Cost scenario is below captured modeled entry components')
            gross = spread_payoff(proposal,quote_map,roundtrip_cost_paise=scenario['roundtrip_cost_paise'])
            bound_cost = dict(source=scenario['source'],roundtrip_cost_paise=scenario['roundtrip_cost_paise'],
                basis='user_declared_fixed_cost_scenario_matched_to_captured_contracts_quantities_quotes_and_valuation',
                limitation='Conditional net payoff only; contract-note totals and variable exercise/closing costs are not verified.')
    records, updated = [], []
    for name, payload in captured.evidence_json:
        if name in TOOLS_BY_ROLE[role]:
            item = AnalyticsEvidence.model_validate_json(payload)
            handoff = dict(schema_version='proposal-handoff.1', proposal=proposal.model_dump(mode='json'),
                assessment='CANNOT_ASSESS', basis='hypothetical_increment_only',
                reason='verified_broker_costs_margin_and_complete_account_aggregation_not_captured',
                gross_terminal_payoff=gross,entry_fee_estimate=entry_fees,cost_scenario=bound_cost)
            if role=='portfolio_risk' and name=='run_spot_vix_cvar_stress_matrix':
                scenario,reason = combined_stress_scenario(proposal,OptionsContext.model_validate_json(captured.context_json),quant_inputs,valuation_time)
                handoff['combined_supplied_position_stress'] = scenario
                handoff['combined_stress_unavailable_reason'] = reason
            identity = uuid5(NAMESPACE_URL,f'{item.evidence_id}:{proposal.proposal_id}:{role}:handoff.1')
            item = item.model_copy(update={'evidence_id':identity,
                'metrics':{**item.metrics,'proposal_handoff':handoff},
                'coverage':{**item.coverage,'proposal_assessment':'unavailable','existing_metrics_basis':'original_capture_before_proposal'},
                'unavailable_reasons':{**item.unavailable_reasons,'post_proposal_assessment':handoff['reason']},
                'limitations':(*item.limitations,'Proposal is hypothetical. Original metrics are not a combined-account or post-proposal assessment.'),
                'status':'PARTIAL', 'source_refs':tuple(dict.fromkeys((*item.source_refs,str(proposal.evidence_id))))})
            payload = item.model_dump_json()
            updated.append(item)
        records.append((name,payload))
    return CapturedAnalytics(captured.owner_id,captured.session_generation,captured.context_json,tuple(records),captured.input_dataset_id), tuple(updated)


def combined_stress_scenario(proposal,context,inputs,valuation_time):
    if not inputs or not inputs.get('risk_positions') or not inputs.get('surface_rows') or inputs.get('surface_spot') is None or valuation_time is None:
        return None,'aligned_existing_positions_and_per_contract_pricing_required'
    if abs((proposal.valued_at-valuation_time).total_seconds())>10:
        return None,'pricing_and_position_marks_not_same_capture_window'
    if any(leg.underlying_key not in (f'nse_fo:OPTIDX:{context.underlying}',f'nse_fo:OPTSTK:{context.underlying}') for leg in proposal.legs):
        return None,'canonical_underlying_link_not_established'
    surface = {row['contract_id']:row for row in inputs['surface_rows']}
    positions = {row['contract_id']:dict(row) for row in inputs['risk_positions']}
    for leg in proposal.legs:
        row = surface.get(leg.contract_id)
        if row is None:
            return None,'per_proposal_contract_iv_forward_rate_history_unavailable'
        if row['side']!=leg.option_type or Decimal(str(row['strike']))!=leg.strike or row['expiry_at'].astimezone(ZoneInfo('Asia/Kolkata')).date()!=leg.expiry:
            raise ValueError('Declared pricing contradicts selected contract identity')
        mark = dict(contract_id=leg.contract_id,underlying=context.underlying,kind='option',quantity=leg.quantity if leg.side=='BUY' else -leg.quantity,
            spot=inputs['surface_spot'],forward=row['forward'],strike=row['strike'],tau=max(0,(row['expiry_at']-valuation_time).total_seconds()/(365*86400)),
            iv=row['iv'],rate=row['rate'],option_type=leg.option_type)
        prior = positions.get(leg.contract_id)
        if prior is not None:
            if any(prior.get(key)!=value for key,value in mark.items() if key not in ('quantity','contract_id')):
                raise ValueError('Conflicting existing and proposed contract marks')
            mark['quantity'] += prior['quantity']
        positions[leg.contract_id] = mark
    combined = list(positions.values())
    result = stress_matrix(combined)
    if inputs.get('risk_history') is not None:
        result['historical_tail'] = historical_repricing(combined,inputs['risk_history'])
    result.update(basis='user_declared_existing_positions_plus_hypothetical_proposal',complete_account_coverage=False,
        valuation_time=valuation_time.isoformat(),position_count=len(combined))
    return result,None
