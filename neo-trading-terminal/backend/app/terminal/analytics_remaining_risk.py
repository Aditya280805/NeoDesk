"""Pure scenario evaluation; missing source inputs never become zero risk."""
from datetime import datetime
from zoneinfo import ZoneInfo
from .analytics_remaining_contracts import CapturedRiskBundle
from .analytics_contracts import StrategyProposal
from .quant_risk import stress_matrix
from .quant_compliance import compliance_checks

def evaluate_remaining_risk(bundle: CapturedRiskBundle, proposal: StrategyProposal | None = None, *, evidence_id=None) -> dict:
    if not isinstance(bundle,CapturedRiskBundle):
        raise TypeError('Expected captured risk bundle')
    # Revalidate even if a caller used model_copy without validation.
    bundle = CapturedRiskBundle.model_validate(bundle.model_dump())
    inventory = {p['contract_id']:dict(p) for p in bundle.positions}
    if proposal is not None:
        if proposal.valued_at > bundle.as_of:
            raise ValueError('Cross-evidence or contradictory proposal rejected')
        if evidence_id is None or str(proposal.evidence_id)!=str(evidence_id):
            raise ValueError('Proposal evidence binding required')
        for leg in proposal.legs:
            row = inventory.get(leg.contract_id)
            if row is None:
                raise ValueError('Captured pricing required for every proposal contract')
            expiry = datetime.fromisoformat(row['expiry_at']) if isinstance(row.get('expiry_at'),str) else row.get('expiry_at')
            if (row['kind']!='option' or row['underlying']!=leg.underlying_key or
                float(row['strike'])!=float(leg.strike) or row['option_type']!=leg.option_type or
                expiry is None or expiry.astimezone(ZoneInfo('Asia/Kolkata')).date()!=leg.expiry):
                raise ValueError('Proposal contract metadata contradicts capture')
            row['quantity'] += leg.quantity if leg.side=='BUY' else -leg.quantity
    reasons = {}
    if bundle.account_coverage!='complete':
        reasons['account_coverage']='account_coverage_is_'+bundle.account_coverage
    if 'funds' in bundle.missing_inputs: reasons['funds_missing']='funds_source_unavailable'
    if 'overlapping_holdings' in bundle.missing_inputs: reasons['coverage']='overlapping_holdings'
    positions = []
    for row in inventory.values():
        row = dict(row)
        if row['kind']=='option':
            expiry = datetime.fromisoformat(row['expiry_at']) if isinstance(row['expiry_at'],str) else row['expiry_at']
            row['tau']=(expiry-bundle.as_of).total_seconds()/(365*86400)
            if row['tau']<=0:
                reasons['stress_matrix']='expired_option_requires_settlement_inputs'
        positions.append(row)
    stress = None
    if positions and 'stress_matrix' not in reasons:
        stress=stress_matrix(positions)
    elif not positions:
        reasons['stress_matrix']='captured_positions_unavailable'
    worst = stress['worst_case_scenario']['pnl'] if stress else None
    reasons['aggregate_futeq']='verified_delta_multiplier_and_underlying_aggregation_required'
    reasons['net_stress_worst_case']='complete_bound_cost_inputs_required'
    reasons['available_margin_paise']='verified_margin_source_required'
    compliance = compliance_checks(positions,{'declared_records':list(bundle.rules),'as_of':bundle.as_of.isoformat()}) if bundle.rules else None
    return dict(schema_version='remaining-risk.1',
        coverage=dict(account_coverage=bundle.account_coverage,proposal_included=proposal is not None,
                      position_count=len(positions),source_count=len(bundle.sources),missing_inputs=bundle.missing_inputs),
        metrics=dict(combined_inventory=tuple(inventory.values()),
            gross_metrics=dict(aggregate_futeq=None,gross_stress_worst_case=worst,max_stress_loss=stress['max_stress_loss'] if stress else None),
            net_metrics=dict(aggregate_futeq=None,net_stress_worst_case=None,net_max_loss=None,cost_paise=None),
            cost_paise=None,stress_matrix=stress,compliance_findings=compliance['findings'] if compliance else [],available_margin_paise=None),
        unavailable_reasons=reasons,source_refs=tuple(s.source+':'+s.revision for s in bundle.sources),
        limitations=['Scenario repricing only; declared source coverage is not independently certified. Exchange margin and delta exposure require their own verified inputs.'])

