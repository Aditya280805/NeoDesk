from datetime import UTC,datetime
from app.terminal.analytics_account_sources import declared_account_risk

def test_declared_history_never_promotes_complete_account_coverage():
    result=declared_account_risk(7,'session',datetime.now(UTC),[dict(contract_id='cash',underlying='ABC',kind='equity',quantity=1,spot=100)],'dataset:1')
    assert result['coverage']['account_coverage']=='partial'
    assert result['metrics']['gross_metrics']['max_stress_loss']==5
    assert result['metrics']['available_margin_paise'] is None
