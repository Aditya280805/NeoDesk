"""Server-only macro-tool calculation dispatch over captured validated inputs.

Call in a bounded worker. This module never fetches, authorizes, or executes trades.
Raw model arguments must never be used as this function's input bundle.
"""
from datetime import UTC, datetime
from uuid import uuid4, UUID

from .analytics_contracts import AnalyticsEvidence, sanitize_quant_payload
from .analytics_runtime import TOOLS_BY_ROLE
from .quant_technical import technical_regime
from .quant_surface import volatility_surface
from .quant_microstructure import oi_microstructure
from .quant_attribution import portfolio_attribution
from .quant_compliance import compliance_checks
from .quant_risk import stress_matrix, historical_repricing
from .quant_proposals import spread_payoff

REQUIRED = {
    'get_technical_regime_snapshot': ('bars',),
    'get_vol_surface_and_greeks': ('surface_rows','forward','rate','as_of'),
    'get_nse_oi_microstructure': ('chain_rows',),
    'get_participant_fii_dii_flow': ('participant_report',),
    'compute_indian_statutory_costs_and_payoff': ('selected_proposal','quotes'),
    'get_portfolio_attribution_and_rebalance': ('verified_returns',),
    'check_sebi_and_mwpl_compliance': ('risk_positions','rules'),
    'run_spot_vix_cvar_stress_matrix': ('risk_positions',),
}


def calculate_evidence(name, inputs, *, source_refs, observed_at, candidates=(), evidence_id=None):
    if name not in REQUIRED:
        raise ValueError('Unknown analytics tool')
    identity = UUID(str(evidence_id)) if evidence_id is not None else uuid4()
    if any(candidate.evidence_id!=identity for candidate in candidates):
        raise ValueError('Candidates must be bound to the captured tool evidence identity')
    missing = [key for key in REQUIRED[name] if inputs.get(key) is None]
    if not source_refs:
        missing.append('verified_source_reference')
    metrics, reasons, limitations = {},{},[]
    if missing:
        reasons = {key:'required_captured_input_unavailable' for key in missing}
    elif name == 'get_technical_regime_snapshot':
        result = technical_regime(inputs['bars'],vix_history=inputs.get('vix_history',()))
        metrics = {**result.pop('metrics'),'regime':result.pop('regime'),'patterns':result.pop('patterns')}
        reasons = result['unavailable_reasons']
    elif name == 'get_vol_surface_and_greeks':
        metrics = volatility_surface(inputs['surface_rows'],forward=inputs['forward'],rate=inputs['rate'],as_of=inputs['as_of'],
            iv_history=inputs.get('iv_history',()),realized_volatility=inputs.get('realized_volatility'),pricing_by_expiry=inputs.get('pricing_by_expiry'))
    elif name == 'get_nse_oi_microstructure':
        metrics = oi_microstructure(inputs['chain_rows'])
    elif name == 'get_participant_fii_dii_flow':
        # Supplied only by ParticipantReports parser/cache, never inferred from prices.
        metrics = dict(inputs['participant_report'])
    elif name == 'compute_indian_statutory_costs_and_payoff':
        metrics = spread_payoff(inputs['selected_proposal'],inputs['quotes'],roundtrip_cost_paise=inputs.get('roundtrip_cost_paise'))
    elif name == 'get_portfolio_attribution_and_rebalance':
        metrics = portfolio_attribution(inputs['verified_returns'],benchmark=inputs.get('benchmark_returns'),bank_benchmark=inputs.get('bank_returns'))
        metrics['hrp_weights'] = inputs.get('verified_hrp_weights')
    elif name == 'check_sebi_and_mwpl_compliance':
        metrics = compliance_checks(inputs['risk_positions'],inputs['rules'])
    elif name == 'run_spot_vix_cvar_stress_matrix':
        metrics = stress_matrix(inputs['risk_positions'])
        if inputs.get('risk_history') is not None:
            metrics['historical_tail'] = historical_repricing(inputs['risk_positions'],inputs['risk_history'])
    if metrics:
        limitations = metrics.pop('limitations',[])
        reasons.update(metrics.pop('unavailable_reasons',{}))
        reasons.update({key:'required_history_input_or_assumption_unavailable' for key,value in metrics.items() if value is None})
    if observed_at is None:
        limitations.append('Source observation time is unknown; retrieval time does not verify market freshness.')
    option_tool = name in TOOLS_BY_ROLE['options_trading_analysis']
    return AnalyticsEvidence(evidence_id=identity,calculation_version=f'{name}.1',observed_at=observed_at,retrieved_at=datetime.now(UTC),
        source_refs=tuple(source_refs),status='UNAVAILABLE' if missing else 'PARTIAL' if reasons else 'AVAILABLE',
        metrics=sanitize_quant_payload(metrics),unavailable_reasons=reasons,limitations=tuple(limitations),
        candidate_proposals=tuple(candidates) if option_tool else ())
