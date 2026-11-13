from app.terminal.optional_ledger import summarize_ledger
import pytest

def test_optional_ledger_summarizes_cash_movements_without_return_claims():
    result=summarize_ledger('date,type,amount_paise\n2026-01-01,DEPOSIT,10000\n2026-01-02,WITHDRAWAL,2000\n')
    assert result['net_external_flow_paise']==8000
    assert result['performance_return'] is None

def test_ledger_rejects_unknown_columns_and_invalid_money():
    for value in ('date,type,amount_paise,password\n2026-01-01,DEPOSIT,10,secret',
                  'date,type,amount_paise\n2026-01-01,DEPOSIT,1.2',
                  'date,type,amount_paise\n2026-01-01,DEPOSIT,-1'):
        with pytest.raises(ValueError): summarize_ledger(value)

def test_ledger_import_owner_isolation_and_summary_projection(tmp_path):
    from datetime import UTC,datetime
    from app.terminal.analytics_store import AnalyticsStore
    from app.terminal.analytics_inputs import AnalyticsInputStore,HistoricalAnalyticsInput
    from app.terminal.options_snapshot import OptionsContext
    store=AnalyticsInputStore(AnalyticsStore(tmp_path/'ledger.sqlite3'))
    context=OptionsContext()
    value=HistoricalAnalyticsInput(context=context,provenance='owner upload',licence='owner supplied',observed_at=datetime.now(UTC),
        ledger_csv='date,type,amount_paise\n2026-01-01,DEPOSIT,10000\n')
    saved=store.save(7,value)
    inputs,_,_=store.load(7,saved['dataset_id'],context)
    assert inputs['ledger_summary']['net_external_flow_paise']==10000
    assert 'ledger_csv' not in inputs
    with pytest.raises(ValueError): store.load(8,saved['dataset_id'],context)
