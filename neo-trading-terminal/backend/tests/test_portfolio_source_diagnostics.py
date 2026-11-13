from app.terminal.portfolio_source_diagnostics import source_shape

def test_diagnostics_never_include_account_values_or_unknown_field_names():
    result = source_shape({'data':[{'exchangeSegment':'nse_cm','exchangeIdentifier':'SECRET','displaySymbol':'PRIVATE','accountSecret':'TOKEN'}]})
    assert result['known_identity_fields'] == ['displaySymbol','exchangeIdentifier','exchangeSegment']
    assert not any(value in str(result) for value in ('SECRET','PRIVATE','TOKEN','accountSecret'))

def test_empty_and_invalid_envelopes_are_distinct():
    assert source_shape({'data':[]})['rows'] == 0
    assert source_shape({'data':None})['data_type'] == 'none'
    assert source_shape(None)['envelope_type'] == 'none'
