import json
from datetime import datetime, UTC
from uuid import uuid4
import pytest
from pydantic import ValidationError
from app.terminal.portfolio_risk_contracts import RiskPolicySettings, RiskPolicy, RiskPolicyUpdate, RiskFinding, RiskReport, RiskCoverage, PortfolioRiskEnvelope
from app.terminal.portfolio_contracts import PortfolioSnapshot, PortfolioRow, RiskInputs, MarginRiskInput, PnlRiskInput, serialize_snapshot


def test_unset_and_zero_policy():
    policy = RiskPolicy(revision=0)
    assert policy.concentration_max_percent is None
    assert policy.max_observation_age_seconds is None
    assert RiskPolicySettings(concentration_max_percent='0').model_dump(mode='json')['concentration_max_percent'] == '0'
    assert RiskPolicySettings(margin_max_percent='1234567890123456.12345678').margin_max_percent == '1234567890123456.12345678'
    assert RiskPolicySettings(loss_max_amount='0', loss_basis='broker_account_net_pnl', loss_period='broker_trading_day').loss_max_amount == '0'


@pytest.mark.parametrize('value', [0, 1.2, True, False, '', ' ', 'NaN', 'Infinity', '1e2', '1E+20000000', '-1', '1234567890123456789012345', '0.123456789'])
def test_decimal_policy_strictness(value):
    with pytest.raises(ValidationError): RiskPolicySettings(margin_max_percent=value)


@pytest.mark.parametrize('field,value', [('concentration_max_percent','100.00000001'), ('expiry_window_days',True), ('expiry_window_days','1'), ('expiry_window_days',1.0), ('expiry_window_days',366), ('expiry_window_days',-1), ('max_observation_age_seconds',0), ('max_observation_age_seconds',86401), ('max_observation_age_seconds','1'), ('concentration_enabled',1), ('loss_enabled','true')])
def test_policy_bounds_and_no_coercion(field,value):
    with pytest.raises(ValidationError): RiskPolicySettings(**{field:value})


def test_policy_unknown_fields_and_loss_triplet():
    for payload in ({'revision':0}, {'owner':1}, {'loss_max_amount':'0'}, {'loss_basis':'broker_account_net_pnl'}, {'loss_max_amount':'0','loss_basis':'invented','loss_period':'broker_trading_day'}):
        with pytest.raises(ValidationError): RiskPolicySettings(**payload)
    for revision in (True, '0', 0.0, -1):
        with pytest.raises(ValidationError): RiskPolicyUpdate(expected_revision=revision, policy={})
    with pytest.raises(ValidationError): RiskPolicy(revision=0).revision = 1


def test_legacy_snapshot_extensions_omitted_and_roundtrip():
    now=datetime.now(UTC)
    snapshot=PortfolioSnapshot(retrieval_started_at=now,retrieval_finished_at=now,source_observed_at=now)
    row=PortfolioRow(row_id='holdings:0')
    assert 'risk_inputs' not in snapshot.model_dump()
    assert 'underlying_key' not in row.model_dump()
    assert 'underlying_identity_basis' not in row.model_dump()
    wire=json.loads(serialize_snapshot(snapshot))
    assert 'risk_inputs' not in wire
    assert PortfolioSnapshot.model_validate(wire).model_dump(mode='json') == wire


def test_typed_risk_inputs_are_strict_and_separate():
    risk=RiskInputs(margin=MarginRiskInput(used_margin='0',total_margin=None), pnl=PnlRiskInput(account_net_pnl='-2'))
    assert risk.model_dump(mode='json')['margin']['used_margin']=='0'
    assert risk.margin.total_margin is None and risk.pnl.source_timestamp is None
    for value in (0, True, '1e2'):
        with pytest.raises(ValidationError): MarginRiskInput(used_margin=value)
    with pytest.raises(ValidationError): RiskInputs(margin={'account_net_pnl':'1'})
    with pytest.raises(ValidationError): PnlRiskInput(raw={})


def test_report_envelope_and_strict_values():
    now=datetime.now(UTC)
    snapshot=PortfolioSnapshot(retrieval_started_at=now,retrieval_finished_at=now,source_observed_at=now)
    findings=[RiskFinding(code=code,enabled=True,outcome='cannot_assess',reason_codes=['limit_not_configured']) for code in ('concentration','expiry','margin','loss')]
    report=RiskReport(evidence_id=snapshot.evidence_id,policy_revision=0,evaluated_at=now,summary='cannot_assess',coverage=RiskCoverage(passed=0,breached=0,cannot_assess=4,disabled=0),findings=findings)
    envelope=PortfolioRiskEnvelope(**snapshot.model_dump(),risk_report=report)
    assert envelope.model_dump(mode='json')['risk_report']['schema_version']=='portfolio-risk.v1'
    assert 'snapshot' not in envelope.model_dump()
    with pytest.raises(ValidationError): RiskFinding(code='loss',enabled=True,outcome='pass',measured=0)
    with pytest.raises(ValidationError): RiskReport(**{**report.model_dump(),'policy_revision':True})
    with pytest.raises(ValidationError): RiskReport(**{**report.model_dump(),'findings':findings[:3]})
