from app.terminal.optional_ledger import summarize_ledger
from app.terminal.optional_ledger import normalize_ledger_csv
import pytest

def test_explicit_column_type_date_and_rupee_mapping():
    text='When,Category,Value,Private\n13/11/2026,Money In,125.50,SECRET\n'
    canonical=normalize_ledger_csv(text,dict(date_column='When',type_column='Category',amount_column='Value',unit='INR',date_format='%d/%m/%Y',type_values={'Money In':'DEPOSIT'}))
    assert 'SECRET' not in canonical and 'Private' not in canonical
    assert summarize_ledger(canonical)['net_external_flow_paise']==12550
    from datetime import UTC,datetime
    from app.terminal.analytics_inputs import HistoricalAnalyticsInput
    from app.terminal.options_snapshot import OptionsContext
    value=HistoricalAnalyticsInput(context=OptionsContext(),provenance='upload',licence='owner',observed_at=datetime.now(UTC),ledger_csv=text,
        ledger_mapping=dict(date_column='When',type_column='Category',amount_column='Value',unit='INR',date_format='%d/%m/%Y',type_values={'Money In':'DEPOSIT'}))
    assert 'SECRET' not in value.model_dump_json() and value.ledger_mapping is None

def test_mapping_never_guesses_type_or_rounds_fractional_paise():
    mapping=dict(date_column='D',type_column='T',amount_column='A',unit='INR')
    with pytest.raises(ValueError): normalize_ledger_csv('D,T,A\n2026-01-01,UNKNOWN,1',mapping)
    with pytest.raises(ValueError): normalize_ledger_csv('D,T,A\n2026-01-01,DEPOSIT,1.001',mapping)

def test_separate_debit_credit_columns_require_explicit_direction():
    mapping=dict(date_column='Date',type_column='Type',debit_column='Debit',credit_column='Credit',unit='INR')
    text='Date,Type,Debit,Credit\n2026-01-01,DEPOSIT,,100\n2026-01-02,CHARGE,2,\n'
    result=summarize_ledger(normalize_ledger_csv(text,mapping))
    assert result['net_external_flow_paise']==10000
    assert result['totals_paise']['CHARGE']==200
    with pytest.raises(ValueError): normalize_ledger_csv('Date,Type,Debit,Credit\n2026-01-01,DEPOSIT,2,100',mapping)
    with pytest.raises(ValueError): normalize_ledger_csv('Date,Type,Debit,Credit\n2026-01-01,DEPOSIT,2,',mapping)

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
    assert store.list_owned(8)==[]
    assert not store.delete_owned(8,saved['dataset_id'])
    assert store.delete_owned(7,saved['dataset_id'])
    assert store.list_owned(7)==[]
    with pytest.raises(ValueError): store.load(7,saved['dataset_id'],context)
