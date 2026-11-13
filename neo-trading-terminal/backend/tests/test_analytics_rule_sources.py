from app.terminal.analytics_rule_sources import map_published_bans

def master(kind='OPTSTK',underlying='KAYNES'):
    return dict(id='nse_fo|1',exchange='nse_fo',token='1',underlying=underlying,
        source_metadata={'source':'kotak-scrip-master','pInstType':kind},
        identity_source_fields={'pSymbol':'1','pExchSeg':'nse_fo','pSymbolName':underlying})

def test_exact_master_underlying_maps_stock_ban():
    result = map_published_bans([{'contract_id':'nse_fo|1','underlying':'KAYNES'}],{'symbols':['KAYNES']},lambda _:master())
    assert result[0]['ban_active'] is True

def test_index_excluded_and_conflicting_identity_unavailable():
    row = {'contract_id':'nse_fo|1','underlying':'NIFTY'}
    result = map_published_bans([row],{'symbols':['NIFTY']},lambda _:master('OPTIDX','NIFTY'))
    assert result[0]['status'] == 'not_applicable'
    result = map_published_bans([row],{'symbols':['KAYNES']},lambda _:master())
    assert result[0]['status'] == 'unavailable' and result[0]['ban_active'] is None
