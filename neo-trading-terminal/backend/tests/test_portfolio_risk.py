import json
from datetime import datetime, timedelta, timezone, date
from decimal import Decimal
from pathlib import Path
import pytest
from app.terminal.portfolio_contracts import PortfolioSnapshot, PortfolioSection, PortfolioRow, RiskInputs, MarginRiskInput, PnlRiskInput, ValueProvenance
from app.terminal.portfolio_risk_contracts import RiskPolicy
from app.terminal.portfolio_risk import evaluate_portfolio_risk

NOW=datetime(2026,10,29,12,tzinfo=timezone.utc)
def policy(**kw):
    return RiskPolicy(revision=1, **({'concentration_max_percent':'60','expiry_window_days':2,'margin_max_percent':'50','loss_max_amount':'10','loss_basis':'broker_account_net_pnl','loss_period':'broker_trading_day','max_observation_age_seconds':60}|kw))
def row(i, value='60', **kw):
    return PortfolioRow(**({'row_id':str(i),'quantity':'1','market_value':value,'currency':'INR','identity_verified':True,'underlying_key':str(i),'underlying_identity_basis':'catalogue_match','contract_type':'EQUITY'}|kw))
def snapshot(rows=None, positions=None, **kw):
    return PortfolioSnapshot(retrieval_started_at=NOW,retrieval_finished_at=NOW,source_observed_at=NOW,sections={n:PortfolioSection(state='available',rows=r,retrieval_started_at=NOW,retrieval_finished_at=NOW) for n,r in [('holdings',rows if rows is not None else [row(1),row(2,'40')]),('positions',positions or []),('funds',[])]},**kw)
def check(s=None,p=None,t=NOW,code='concentration'):
    return next(f for f in evaluate_portfolio_risk(s or snapshot(),p or policy(),t).findings if f.code==code)

@pytest.mark.parametrize('case',json.loads((Path(__file__).parents[1]/'evals/portfolio_risk_cases.json').read_text()))
def test_independent_arithmetic(case):
    a,b=map(Decimal,case['values'])
    assert a*100==Decimal(case['left'])
    assert Decimal(case['limit'])*(a+b)==Decimal(case['right'])
    f=check(snapshot([row(1,str(a)),row(2,str(b))]),policy(concentration_max_percent=case['limit']))
    assert f.outcome==case['outcome']

@pytest.mark.parametrize('mode',['partial','zero','negative','unknown','duplicate','contradiction','huge'])
def test_conservative_concentration(mode):
    s=snapshot()
    if mode=='partial': s.sections['holdings'].state='partial'
    if mode=='zero': s.sections['holdings'].rows=[row(1,'0')]
    if mode=='negative': s.sections['holdings'].rows=[row(1,'-1')]
    if mode=='unknown': s.sections['holdings'].rows[0].underlying_key=None
    if mode=='duplicate': s.sections['holdings'].rows[1].underlying_key='1'
    if mode=='contradiction': s.sections['holdings'].rows[0].quantity=Decimal(0)
    if mode=='huge': s.sections['holdings'].rows[0].market_value=Decimal('1e100000')
    assert check(s).outcome=='cannot_assess'
def test_disjoint_lots():
    s=snapshot([row(1,'30',underlying_key='A',inventory_coverage='disjoint',inventory_coverage_basis='source_lots'),row(2,'30',underlying_key='A',inventory_coverage='disjoint',inventory_coverage_basis='source_lots'),row(3,'40')])
    assert check(s).outcome=='pass'
    assert check(s).numerator=='60'

@pytest.mark.parametrize('offset,outcome,reason',[(-1,'breach','expired_open'),(0,'breach','expiry_within_window'),(2,'breach','expiry_within_window'),(3,'pass',None)])
@pytest.mark.parametrize('qty',['1','-1'])
def test_expiry_boundaries(offset,outcome,reason,qty):
    f=check(snapshot(positions=[row(1,contract_type='FUT',quantity=qty,expiry=date(2026,10,29)+timedelta(days=offset))]),code='expiry')
    assert f.outcome==outcome
    if reason: assert reason in f.reason_codes
@pytest.mark.parametrize('qty,kind,outcome',[('0',None,'pass'),(None,'FUT','cannot_assess'),('1',None,'cannot_assess')])
def test_expiry_unknown(qty,kind,outcome):
    assert check(snapshot(positions=[row(1,quantity=qty,contract_type=kind)]),code='expiry').outcome==outcome
def test_partial_known_expiry_breach_and_rollover():
    s=snapshot(positions=[row(1,contract_type='OPT',expiry=date(2026,10,29))]);s.sections['positions'].state='partial'
    f=check(s,t=datetime(2026,10,29,18,30,tzinfo=timezone.utc),p=policy(max_observation_age_seconds=86400),code='expiry')
    assert f.outcome=='breach' and 'expired_open' in f.reason_codes

@pytest.mark.parametrize('delta,outcome',[(60,'pass'),(61,'cannot_assess'),(-1,'cannot_assess')])
def test_age(delta,outcome): assert check(t=NOW+timedelta(seconds=delta)).outcome==outcome
def test_time_and_unset_disabled():
    s=snapshot();s.sections['holdings'].retrieval_started_at=NOW.replace(tzinfo=None)
    assert check(s).outcome=='cannot_assess'
    assert check(p=policy(max_observation_age_seconds=None)).outcome=='cannot_assess'
    assert check(p=policy(concentration_max_percent=None)).outcome=='cannot_assess'
    r=evaluate_portfolio_risk(snapshot(),policy(**{n+'_enabled':False for n in ['concentration','expiry','margin','loss']}),NOW)
    assert r.summary=='cannot_assess' and r.coverage.disabled==4
    with pytest.raises(ValueError): evaluate_portfolio_risk(snapshot(),policy(),NOW.replace(tzinfo=None))

def inputs():
    prov=lambda names:{n:ValueProvenance(source='provider',input_paths=['synthetic.'+n],basis='synthetic_test') for n in names}
    return RiskInputs(margin=MarginRiskInput(used_margin='50',total_margin='100',currency='INR',basis='broker_account_total_margin',period='point_in_time',source_timestamp=NOW,provenance=prov(['used_margin','total_margin'])),pnl=PnlRiskInput(account_net_pnl='-10',currency='INR',basis='broker_account_net_pnl',period='broker_trading_day',period_start=datetime(2026,10,28,18,30,tzinfo=timezone.utc),period_end=datetime(2026,10,29,18,30,tzinfo=timezone.utc),source_timestamp=NOW,provenance=prov(['account_net_pnl'])))
@pytest.mark.parametrize('code',['margin','loss'])
def test_financial_equality_and_missing(code):
    assert check(snapshot(risk_inputs=inputs()),code=code).outcome=='pass'
    f=check(code=code);assert f.outcome=='cannot_assess' and f.measured is None
@pytest.mark.parametrize('code,field,value',[('margin','basis','provider_reported'),('margin','currency','USD'),('margin','period','unknown'),('margin','total_margin','0'),('margin','total_margin','-1'),('loss','basis','unknown'),('loss','currency','USD'),('loss','period','unknown'),('loss','source_timestamp',NOW-timedelta(seconds=61)),('margin','source_timestamp',NOW+timedelta(seconds=1))])
def test_financial_bad_metadata(code,field,value):
    records=inputs();record=getattr(records,'pnl' if code=='loss' else code);object.__setattr__(record,field,value)
    assert check(snapshot(risk_inputs=records),code=code).outcome=='cannot_assess'
def test_profit_and_breaches():
    records=inputs();object.__setattr__(records.pnl,'account_net_pnl','5')
    assert check(snapshot(risk_inputs=records),code='loss').measured=='0'
    object.__setattr__(records.pnl,'account_net_pnl','-11');object.__setattr__(records.margin,'used_margin','51')
    assert check(snapshot(risk_inputs=records),code='loss').outcome=='breach'
    assert check(snapshot(risk_inputs=records),code='margin').outcome=='breach'

def test_cached_original_time_and_section_order():
    s=snapshot();s.cache_age_seconds=Decimal(0)
    s.sections['holdings'].retrieval_started_at=NOW-timedelta(seconds=61)
    assert check(s).reason_codes==['stale_observation']
    s.sections['holdings'].retrieval_started_at=NOW+timedelta(seconds=1)
    assert check(s).reason_codes==['invalid_observation_time']

@pytest.mark.parametrize('value',[True,'NaN','Infinity','1e999999',object()])
def test_hostile_mutated_row_value(value):
    s=snapshot();object.__setattr__(s.sections['holdings'].rows[0],'market_value',value)
    f=check(s)
    assert f.outcome=='cannot_assess' and f.measured is None
    assert f.reason_codes==['calculation_unavailable']

def test_huge_expiry_quantity():
    s=snapshot(positions=[row(1,contract_type='FUT',expiry=date(2026,10,29),quantity='1e100000')])
    assert check(s,code='expiry').reason_codes==['calculation_unavailable']

def test_shallow_provenance_mutation_and_wrong_day():
    records=inputs();records.margin.provenance['used_margin']='untrusted'
    assert check(snapshot(risk_inputs=records),code='margin').outcome=='cannot_assess'
    records=inputs();object.__setattr__(records.pnl,'period_start',NOW-timedelta(days=1))
    assert check(snapshot(risk_inputs=records),code='loss').reason_codes==['unsupported_period']

def test_expiry_partial_unknown_and_empty():
    s=snapshot();s.sections['positions'].state='partial'
    assert check(s,code='expiry').outcome=='cannot_assess'
    assert check(snapshot(),code='expiry').outcome=='pass'
    assert check(snapshot([])).outcome=='cannot_assess'

def test_report_identity_and_coverage(monkeypatch):
    from uuid import UUID
    import app.terminal.portfolio_risk as module
    monkeypatch.setattr(module,'new_report_id',lambda:UUID(int=1))
    s=snapshot(risk_inputs=inputs())
    a=evaluate_portfolio_risk(s,policy(),NOW);b=evaluate_portfolio_risk(s,policy(),NOW)
    assert a.model_dump()==b.model_dump()
    assert a.coverage.passed==4 and a.summary=='pass'

def test_ambient_decimal_context_is_isolated(monkeypatch):
    from decimal import localcontext, Inexact, Rounded, ROUND_DOWN, ROUND_UP
    from uuid import UUID
    import app.terminal.portfolio_risk as module
    monkeypatch.setattr(module,'new_report_id',lambda:UUID(int=2))
    s=snapshot([row(1,'2'),row(2,'1')]);p=policy(concentration_max_percent='66.66666666')
    expected=evaluate_portfolio_risk(s,p,NOW).model_dump()
    for rounding in (ROUND_DOWN,ROUND_UP):
        with localcontext() as ambient:
            ambient.prec=9;ambient.rounding=rounding
            ambient.traps[Inexact]=True;ambient.traps[Rounded]=True
            ambient.clear_flags()
            before=(ambient.copy(),dict(ambient.flags),dict(ambient.traps))
            actual=evaluate_portfolio_risk(s,p,NOW).model_dump()
            assert actual==expected
            assert ambient.prec==before[0].prec and ambient.rounding==before[0].rounding
            assert dict(ambient.flags)==before[1] and dict(ambient.traps)==before[2]

def test_mixed_coverage_and_summary_precedence():
    s=snapshot([row(1,'61'),row(2,'39')])
    report=evaluate_portfolio_risk(s,policy(loss_enabled=False),NOW)
    assert report.summary=='breach'
    assert report.coverage.model_dump()=={'passed':1,'breached':1,'cannot_assess':1,'disabled':1}
    report=evaluate_portfolio_risk(snapshot(),policy(loss_enabled=False),NOW)
    assert report.summary=='cannot_assess'
    assert report.coverage.model_dump()=={'passed':2,'breached':0,'cannot_assess':1,'disabled':1}

