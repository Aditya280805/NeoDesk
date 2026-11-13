from app.terminal.portfolio_source_diagnostics import source_shape

def test_diagnostics_never_include_account_values_or_unknown_field_names():
    result = source_shape({'data':[{'exchangeSegment':'nse_cm','exchangeIdentifier':'SECRET','displaySymbol':'PRIVATE','accountSecret':'TOKEN'}]})
    assert result['known_identity_fields'] == ['displaySymbol','exchangeIdentifier','exchangeSegment']
    assert not any(value in str(result) for value in ('SECRET','PRIVATE','TOKEN','accountSecret'))

def test_empty_and_invalid_envelopes_are_distinct():
    assert source_shape({'data':[]})['rows'] == 0
    assert source_shape({'data':None})['data_type'] == 'none'
    assert source_shape(None)['envelope_type'] == 'none'

def test_diagnostics_classify_only_documented_empty_code():
    assert source_shape({'stat':'Not_Ok','stCode':5203,'errMsg':'private'})['documented_empty'] is True
    assert source_shape({'stat':'Not_Ok','stCode':401,'errMsg':'No Data'})['documented_empty'] is False

def test_empty_normalization_is_scoped_and_does_not_hide_conflicts():
    from app.terminal.portfolio_source_diagnostics import normalized_empty
    empty = {'stat':'Not_Ok','stCode':5203}
    assert normalized_empty('positions',empty) == {'data':[]}
    assert normalized_empty('order_report',empty) == {'data':[]}
    assert normalized_empty('limits',empty) is None
    assert normalized_empty('positions',dict(empty,error='failed')) is None
    assert normalized_empty('positions',dict(empty,data=[{'qty':1}])) is None
