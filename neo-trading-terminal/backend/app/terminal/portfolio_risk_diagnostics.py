"""Allowlisted diagnostics shared by runtime and offline evaluation; no I/O."""


def risk_diagnostics(report, duration_ms, *, failure_stage=None, evidence_id=None, policy=None):
    """Return operational metadata without findings, provider text or exceptions."""
    enabled_count = None
    if report is not None:
        evidence_id = report.evidence_id
        policy_revision = report.policy_revision
        enabled_count = report.coverage.enabled
    else:
        policy_revision = policy.revision if policy is not None else None
        if policy is not None:
            enabled_count = sum(
                getattr(policy, code + '_enabled')
                for code in ('concentration', 'expiry', 'margin', 'loss')
            )
    outcome = 'operational_failure'
    if failure_stage is None and report is not None:
        outcome = report.summary
    return {
        'report_id': str(report.report_id) if report is not None else None,
        'evidence_id': str(evidence_id) if evidence_id is not None else None,
        'policy_revision': policy_revision,
        'calculation_version': report.calculation_version if report is not None else 'portfolio-risk.1',
        'enabled_count': enabled_count,
        'assessed_count': report.coverage.assessed if report is not None else None,
        'duration_ms': round(duration_ms, 2),
        'outcome': outcome,
        'failure_stage': failure_stage,
    }
