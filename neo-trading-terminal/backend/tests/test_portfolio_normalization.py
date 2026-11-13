from datetime import UTC, datetime
from decimal import Decimal
from app.terminal.portfolio_contracts import SectionObservation
from app.terminal.portfolio_normalization import normalize_portfolio, resolve_portfolio_instrument, to_legacy_portfolio

NOW = datetime(2026, 10, 28, tzinfo=UTC)
def snap(section, rows):
    return normalize_portfolio({section: SectionObservation(raw={'data': rows})}, [], observed_at=NOW)
def holding(**kw):
    return dict(exchangeSegment='nse_cm', displaySymbol='ABC', quantity='3', averagePrice='0.10', ltp='0.20', **kw)
def position(**kw):
    return dict(exSeg='nse_fo', netQty='2', ltp='10', cfBuyAmt='0', buyAmt='12', cfSellAmt='0', sellAmt='0', **kw)

def test_empty_failed_and_invalid_sections_are_distinct():
    s=normalize_portfolio({'holdings':SectionObservation(raw={'data':[]}), 'positions':SectionObservation(error_code='private error'), 'orders':SectionObservation(raw={'oops':[]})},[],observed_at=NOW)
    assert [s.sections[k].state for k in ('holdings','positions','orders')]==['available','unavailable','invalid']
    assert s.summary['holdings_value']==0
    assert 'private error' not in s.model_dump_json()

def test_missing_quantity_keeps_issue_and_blocks_aggregate():
    s=snap('holdings',[holding(),dict(exchangeSegment='nse_cm', averagePrice='2',ltp='3')])
    assert len(s.sections['holdings'].rows)==2
    assert s.sections['holdings'].state=='partial'
    assert s.summary['holdings_value'] is None
    assert s.sections['holdings'].rows[1].issues
    assert len(to_legacy_portfolio(s)['holdings'])==2
    assert snap('holdings',[dict(exchangeSegment='nse_cm',quantity=0)]).sections['holdings'].rows[0].quantity==0

def test_unknown_side_stays_unknown():
    s=snap('orders',[dict(trnsTp='?',qty=1)])
    assert to_legacy_portfolio(s)['orders'][0]['side']=='UNKNOWN'

def test_missing_multiplier_blocks_derived_position_pnl():
    r=snap('positions',[position()]).sections['positions'].rows[0]
    assert r.calculated_pnl is None
    assert any(i.code=='missing_multiplier' for i in r.issues)

def test_bad_denominator_never_defaults_to_one():
    r=snap('positions',[position(multiplier=1,genNum=1,genDen=0,prcNum=1,prcDen=1)]).sections['positions'].rows[0]
    assert r.multiplier is None and r.calculated_pnl is None
    assert any(i.code=='invalid_denominator' for i in r.issues)

def test_provider_pnl_and_calculated_pnl_keep_distinct_bases():
    r=snap('positions',[position(mtm='9',multiplier=1,genNum=1,genDen=1,prcNum=1,prcDen=1)]).sections['positions'].rows[0]
    assert r.provider_pnl==9 and r.calculated_pnl==8
    assert r.provenance['provider_pnl'].basis != r.provenance['calculated_pnl'].basis
    assert snap('positions',[position(currency='USD',mtm=9)]).sections['positions'].rows[0].calculated_pnl is None

def test_holdings_decimal_rounding_and_provenance():
    r=snap('holdings',[holding()]).sections['holdings'].rows[0]
    assert (r.invested_value,r.market_value,r.calculated_pnl)==(Decimal('.30'),Decimal('.60'),Decimal('.30'))
    assert r.provenance['invested_value'].input_paths==['quantity','averagePrice']
    assert r.provenance['invested_value'].formula_version
    r=snap('holdings',[dict(exchangeSegment='nse_cm',quantity=1,averagePrice='.005',ltp='.015')]).sections['holdings'].rows[0]
    assert r.invested_value==Decimal('.01') and r.market_value==Decimal('.02')

def test_identity_conflict_or_ambiguity_disables_match():
    cat=[dict(id='nse_fo|1',exchange='nse_fo',token='1',symbol='ABC',kind='OPTION',expiry='2026-10-29',strike=100,option_type='CE')]
    assert resolve_portfolio_instrument(dict(exSeg='nse_fo',tok='1',trdSym='OTHER'),cat,holding=False)['identity_status']=='invalid'
    assert resolve_portfolio_instrument(dict(exSeg='nse_fo',trdSym='ABC'),cat+cat,holding=False)['identity_status']=='ambiguous'
    for field,value in [('expiry','2026-11-01'),('strike',200),('option_type','PE')]:
        assert resolve_portfolio_instrument(dict(exSeg='nse_fo',tok='1',**{field:value}),cat,holding=False)['identity_status']=='invalid'
    assert resolve_portfolio_instrument(dict(exSeg='nse_fo',tok='1'),cat,holding=False)['identity_verified'] is False

def test_missing_cash_flow_is_not_zero_and_net_quantity_is_authoritative():
    raw=position(multiplier=1,genNum=1,genDen=1,prcNum=1,prcDen=1,cfBuyQty=99,flBuyQty=1,cfSellQty=0,flSellQty=0)
    del raw['cfBuyAmt']
    r=snap('positions',[raw]).sections['positions'].rows[0]
    assert r.quantity==2 and r.calculated_pnl is None

def test_legacy_catalogue_symbol_link_requires_unique_match():
    cat=[dict(id='nse_cm|1',exchange='nse_cm',token='1',symbol='ABC-EQ')]
    s=normalize_portfolio({'holdings':SectionObservation(raw={'data':[holding()]})},cat,observed_at=NOW)
    assert to_legacy_portfolio(s)['holdings'][0]['instrument_id']=='nse_cm|1'
    assert s.sections['holdings'].rows[0].identity_verified is False

def test_cash_display_symbol_and_eq_trading_symbol_are_equivalent():
    cat=[dict(id='nse_cm|1',exchange='nse_cm',token='1',symbol='ABC-EQ')]
    raw=holding(exchangeIdentifier='1',symbol='ABC-EQ')
    result=resolve_portfolio_instrument(raw,cat,holding=True)
    assert result['identity_basis']=='catalogue_match'
    assert result['identity_status']!='invalid'
    wrong=resolve_portfolio_instrument(holding(exchangeIdentifier='1',symbol='OTHER-EQ'),cat,holding=True)
    assert wrong['identity_status']=='invalid'

def test_unknown_currency_blocks_holdings_totals_and_invalid_rows_preserve_good_rows():
    s=snap('holdings',[holding(currency='USD'),holding(),None])
    assert s.summary['holdings_value'] is None
    assert s.sections['holdings'].rows[1].market_value==Decimal('.60')
    assert len(to_legacy_portfolio(s)['holdings'])==3

def test_all_contract_alias_conflicts_invalidate_even_without_catalogue():
    cat=[dict(id='nse_fo|1',exchange='nse_fo',token='1',symbol='ABC',expiry='2026-10-29',strike=100,option_type='CE',kind='OPTION')]
    for extra in [dict(expiry='2026-10-29',expiryDate='2026-11-01'),dict(strike=100,strikePrice=200),dict(option_type='CE',optionType='PE'),dict(contract_type='OPTION',kind='FUTURE')]:
        for catalogue in (cat,[]):
            result=resolve_portfolio_instrument(dict(exSeg='nse_fo',tok='1',**extra),catalogue,holding=False)
            assert result['identity_status']=='invalid'
            assert result.get('instrument_id') is None
            assert result['identity_basis']!='catalogue_match'

def test_ambiguous_identity_preserves_provider_values_but_blocks_derivation_and_totals():
    cat=[dict(id='nse_cm|1',exchange='nse_cm',token='1',symbol='ABC')]*2
    s=normalize_portfolio({'holdings':SectionObservation(raw={'data':[holding(),holding(holdingCost=1,mktValue=2),dict(exchangeSegment='nse_cm',displaySymbol='OTHER',quantity=1,averagePrice=2,ltp=3)]})},cat,observed_at=NOW)
    rows=s.sections['holdings'].rows
    assert rows[0].invested_value is None and rows[0].market_value is None
    assert rows[1].invested_value==1 and rows[1].market_value==2 and rows[1].calculated_pnl is None
    assert rows[2].calculated_pnl==1
    assert s.summary['holdings_value'] is None and s.summary['holdings_pnl'] is None

def test_decimal_overflow_becomes_row_issue_and_preserves_other_rows():
    s=snap('holdings',[dict(exchangeSegment='nse_cm',quantity='1e999999',averagePrice='1e999999',ltp='1e999999'),holding()])
    r=s.sections['holdings'].rows[0]
    assert r.invested_value is None and r.market_value is None
    assert any(i.code=='calculation_overflow' for i in r.issues)
    assert s.sections['holdings'].rows[1].market_value==Decimal('.60')
    assert s.summary['holdings_value'] is None
    r=snap('positions',[position(multiplier='1e999999',genNum='1e999999',genDen=1,prcNum=1,prcDen=1)]).sections['positions'].rows[0]
    assert r.multiplier is None and any(i.code=='calculation_overflow' for i in r.issues)

def test_decimal_formula_uses_64_digit_context_before_rounding():
    r=snap('positions',[dict(exSeg='nse_fo',netQty=0,ltp=1,cfBuyAmt='10000000000000000000000000000.01',buyAmt=0,cfSellAmt='10000000000000000000000000000.02',sellAmt=0,multiplier=1,genNum=1,genDen=1,prcNum=1,prcDen=1)]).sections['positions'].rows[0]
    assert r.calculated_pnl==Decimal('.01')


def test_final_review_malformed_sides_preserve_other_sections():
    s=normalize_portfolio({
        'holdings':SectionObservation(raw={'data':[holding()]}),
        'positions':SectionObservation(raw={'data':[]}),
        'funds':SectionObservation(raw={'Net':'10'}),
        'orders':SectionObservation(raw={'data':[{'qty':'1','trnsTp':v} for v in ([],{},'B','S')]})},[],observed_at=NOW)
    assert [r.side for r in s.sections['orders'].rows]==['UNKNOWN','UNKNOWN','BUY','SELL']
    assert s.sections['orders'].state=='partial'
    assert all(any(i.code=='unknown_side' for i in r.issues) for r in s.sections['orders'].rows[:2])
    assert s.summary['holdings_value']==Decimal('.60') and s.summary['available']==10


def test_final_review_long_identity_cannot_match_truncated_catalogue():
    raw={'exSeg':'nse_fo','tok':'1'*121,'trdSym':'ABC','qty':'1'}
    catalogue=[{'id':'nse_fo|'+'1'*120,'token':'1'*120,'exchange':'nse_fo','symbol':'ABC'}]
    result=resolve_portfolio_instrument(raw,catalogue,holding=False)
    assert result['identity_basis']!='catalogue_match'
    assert result['token']==raw['tok']


def test_final_review_lot_conflicts_fail_closed():
    catalogue=[{'id':'nse_fo|1','exchange':'nse_fo','symbol':'ABC','lot_size':25}]
    for supplied in ({'lotSize':50},{'lot_size':25,'lotSize':50}):
        raw=dict(exSeg='nse_fo',tok='1',trdSym='ABC',netQty=1,mtm=3,**supplied)
        result=resolve_portfolio_instrument(raw,catalogue,holding=False)
        assert result['identity_status']=='invalid' and 'instrument_id' not in result
        s=normalize_portfolio({'positions':SectionObservation(raw={'data':[raw]})},catalogue,observed_at=NOW)
        assert s.summary['positions_provider_pnl'] is None
    for placeholder in (None,0,1,'',-1):
        c=[dict(catalogue[0],lot_size=placeholder)]
        result=resolve_portfolio_instrument({'exSeg':'nse_fo','tok':'1','trdSym':'ABC','lotSize':50},c,holding=False)
        assert result['identity_status']=='unresolved'


def test_generic_provider_fields_do_not_establish_risk_semantics():
    raw=holding(underlying_key='invented',underlying_identity_basis='provider_reported',inventory_coverage='disjoint')
    s=normalize_portfolio({'holdings':SectionObservation(raw={'data':[raw]}),
        'funds':SectionObservation(raw={'data':{'Net':'100','MarginUsed':'20','RealizedMtomPrsnt':'-1','UnrealizedMtomPrsnt':'-2',
            'total_margin':'120','account_net_pnl':'-3','basis':'broker_account_net_pnl','period':'broker_trading_day'}})},[],observed_at=NOW)
    assert s.risk_inputs is None
    r=s.sections['holdings'].rows[0]
    assert r.underlying_key is None and r.underlying_identity_basis is None
    assert r.inventory_coverage is None and r.inventory_coverage_basis is None
