import threading
import time
from unittest.mock import MagicMock
import pytest
from app.core.config import Settings
from app.terminal.market import Market
from app.terminal.portfolio_service import PortfolioSnapshotService
from app.brokers.base_broker import BrokerError

@pytest.fixture
def setup(tmp_path,monkeypatch):
    from app.terminal.server import create_app
    app=create_app(Settings(_env_file=None,data_dir=tmp_path,environment='test',app_password=None,market_data_source='sample',kotak_consumer_key=None))
    market=app.state.market
    for uid in (1,2):
        sess=market.get_session(uid); sess.broker=MagicMock(is_authenticated=True); sess.source='kotak'
    calls=[]
    def call(method,user_id):
        calls.append((user_id,method))
        return {'Net':'10'} if method=='limits' else {'data':[]}
    monkeypatch.setattr(market,'call',call)
    return market,app.state.store,calls

def fetch(setup,uid=1,**kwargs):
    market,store,_=setup
    return PortfolioSnapshotService(market,store).fetch(uid,expected_generation=market.session_generation(uid),**kwargs)

def test_user_generation_cache_and_forced_refresh(setup):
    a=fetch(setup); b=fetch(setup)
    assert a.evidence_id!=b.evidence_id and a.source_observed_at==b.source_observed_at
    assert len(setup[2])==4
    fetch(setup,2); fetch(setup,force=True)
    assert len(setup[2])==12

def test_collection_partial_failure_and_auth_expiry(setup,monkeypatch):
    market,_,_=setup; original=market.call
    def partial(method,user_id):
        if method=='holdings': raise ValueError('SECRET')
        return original(method,user_id)
    monkeypatch.setattr(market,'call',partial)
    result=fetch(setup)
    assert result.sections['holdings'].state=='unavailable'
    assert 'SECRET' not in result.model_dump_json()
    monkeypatch.setattr(market,'call',lambda *a,**kw: (_ for _ in ()).throw(ValueError('SECRET')))
    with pytest.raises(BrokerError): fetch(setup,force=True)
    def expiry(*a,**kw):
        market.get_session(1).broker.is_authenticated=False
        raise ValueError('SECRET')
    monkeypatch.setattr(market,'call',expiry)
    with pytest.raises(BrokerError): fetch(setup,force=True)

@pytest.mark.parametrize('action',['disconnect','sign_in','connect','broker_login','auth'])
def test_inflight_disconnect_or_reconnect_cannot_publish_old_cache(setup,monkeypatch,action):
    market,store,_=setup; entered=threading.Event(); release=threading.Event(); errors=[]
    def blocked(*a,**kw):
        entered.set(); assert release.wait(5); return {'data':[]}
    monkeypatch.setattr(market,'call',blocked)
    generation=market.session_generation(1)
    def worker():
        try: PortfolioSnapshotService(market,store).fetch(1,expected_generation=generation)
        except BrokerError as exc: errors.append(exc)
    thread=threading.Thread(target=worker); thread.start(); assert entered.wait(5)
    if action=='disconnect': market.disconnect(1)
    elif action=='sign_in':
        from app.terminal.market import UserMarketSession
        replacement=UserMarketSession(market.config); replacement.broker=MagicMock(is_authenticated=True)
        monkeypatch.setattr('app.terminal.market.UserMarketSession',lambda cfg:replacement)
        monkeypatch.setattr(store,'broker_user',lambda *args:{'id':1})
        market.sign_in('key','ucc','mobile','totp','mpin')
    elif action=='connect':
        monkeypatch.setattr(market,'quotes',lambda *a,**kw:[{'ltp':1}]); market.connect('new-key',1)
    elif action=='broker_login': market.broker_login('u','m','t','p',1)
    else:
        market.get_session(1).generation='invalidated'; market.get_session(1).broker.is_authenticated=False
    release.set(); thread.join(5)
    assert not thread.is_alive() and errors
    assert market.session_generation(1)!=generation
    assert market.get_session(1).portfolio_cache is None

def test_deadline_checked_before_each_broker_call(setup,monkeypatch):
    market,_,calls=setup
    clock=[0.]
    monkeypatch.setattr(time,"monotonic",lambda:clock[0])
    def slow(method,user_id,**kwargs):
        calls.append(method)
        clock[0]=2.
        return {'data':[]}
    monkeypatch.setattr(market,'call',slow)
    with pytest.raises(BrokerError,match='deadline'): fetch(setup,deadline_monotonic=1.)
    assert len(calls)==1
    monkeypatch.undo()
    entered=threading.Event(); release=threading.Event()
    def holder():
        with market.call_lock: entered.set(); release.wait(5)
    thread=threading.Thread(target=holder); thread.start(); assert entered.wait(5)
    try:
        with pytest.raises(BrokerError,match='deadline'): fetch(setup,deadline_monotonic=time.monotonic()+.01)
    finally: release.set(); thread.join(5)
    assert len(calls)==1

@pytest.mark.parametrize('payload',[{'data':[{}]*1001},{'data':[{'description':'x'*1048577}]}])
def test_payload_limits_and_long_strings(setup,monkeypatch,payload):
    market,_,_=setup; original=market.call
    monkeypatch.setattr(market,'call',lambda method,user_id:payload if method=='holdings' else original(method,user_id))
    result=fetch(setup)
    assert result.sections['holdings'].state=='invalid'
    assert result.sections['holdings'].issues[0].code=='payload_limit'
    monkeypatch.setattr(market,'call',lambda method,user_id:{'data':[{'trdSym':'x'*500,'qty':'1'}]} if method=='order_report' else original(method,user_id))
    result=fetch(setup,force=True)
    assert result.sections['orders'].rows[0].symbol=='x'*500
    assert not any(i.code=='string_shortened' for i in result.sections['orders'].issues)

def test_real_market_auth_invalidation_advances_generation(setup,monkeypatch):
    market,store,_=setup
    monkeypatch.undo()
    session=market.get_session(1)
    sdk=MagicMock(); sdk.holdings.return_value={'stCode':'401'}
    session.broker._sdk.return_value=sdk
    session.broker.close.side_effect=lambda:setattr(session.broker,'is_authenticated',False)
    generation=market.session_generation(1)
    market.last_request=0
    with pytest.raises(BrokerError):
        PortfolioSnapshotService(market,store).fetch(1,expected_generation=generation)
    assert market.session_generation(1)!=generation
    assert session.portfolio_cache is None


def test_global_lock_deadline_and_event_loop_guard(setup):
    market,store,_=setup; generation=market.session_generation(1)
    entered=threading.Event(); release=threading.Event()
    def holder():
        with market.lock: entered.set(); release.wait(5)
    thread=threading.Thread(target=holder); thread.start(); assert entered.wait(5)
    try:
        with pytest.raises(BrokerError,match='deadline'):
            PortfolioSnapshotService(market,store).fetch(1,expected_generation=generation,deadline_monotonic=time.monotonic()+.01)
    finally: release.set(); thread.join(5)
    import asyncio
    async def event_loop():
        with pytest.raises(RuntimeError,match='worker thread'):
            PortfolioSnapshotService(market,store).fetch(1,expected_generation=generation)
    asyncio.run(event_loop())


def test_throttle_deadline_prevents_network(setup,monkeypatch):
    market,store,_=setup
    monkeypatch.undo()
    session=market.get_session(1); sdk=MagicMock(); session.broker._sdk.return_value=sdk
    market.last_request=time.monotonic()
    with pytest.raises(BrokerError,match='deadline'):
        PortfolioSnapshotService(market,store).fetch(1,expected_generation=market.session_generation(1),deadline_monotonic=time.monotonic()+.1)
    sdk.holdings.assert_not_called()
    assert session.portfolio_cache is None

@pytest.mark.parametrize('action',['connect','broker_login'])
def test_real_late_401_preserves_new_authentication(setup,monkeypatch,action):
    market,store,_=setup; monkeypatch.undo()
    sess=market.get_session(1); old=sess.broker
    entered=threading.Event(); release=threading.Event(); errors=[]
    def stale():
        entered.set(); assert release.wait(5); return {'stCode':'401'}
    old._sdk.return_value.holdings.side_effect=stale
    old.close.side_effect=lambda:setattr(old,'is_authenticated',False)
    generation=market.session_generation(1); market.last_request=0
    def worker():
        try: PortfolioSnapshotService(market,store).fetch(1,expected_generation=generation)
        except BrokerError as exc: errors.append(exc)
    thread=threading.Thread(target=worker); thread.start(); assert entered.wait(5)
    if action=='connect':
        replacement=MagicMock(is_authenticated=True)
        monkeypatch.setattr('app.terminal.market.KotakNeoBroker',lambda cfg:replacement)
        monkeypatch.setattr(market,'quotes',lambda *a,**kw:[{'ltp':1}])
        market.connect('replacement-key',1)
    else:
        old.login.side_effect=lambda *args:setattr(old,'is_authenticated',True)
        assert market.broker_login('u','m','t','p',1)
    current=sess.broker; new_generation=market.session_generation(1)
    current.close.reset_mock()
    release.set(); thread.join(5)
    assert not thread.is_alive() and errors
    assert sess.generation==new_generation
    assert current.is_authenticated
    current.close.assert_not_called()
    assert sess.portfolio_cache is None


def test_actual_call_lifecycle_lock_wait_respects_deadline(setup,monkeypatch):
    market,store,_=setup; monkeypatch.undo()
    original=market.call; entering_call=threading.Event(); lock_held=threading.Event(); release=threading.Event(); done=threading.Event(); errors=[]
    def wrapped(*args,**kwargs):
        entering_call.set(); assert lock_held.wait(5)
        return original(*args,**kwargs)
    monkeypatch.setattr(market,'call',wrapped)
    def holder():
        assert entering_call.wait(5)
        with market.lock:
            lock_held.set(); assert release.wait(5)
    holder_thread=threading.Thread(target=holder); holder_thread.start()
    generation=market.session_generation(1)
    def worker():
        try: PortfolioSnapshotService(market,store).fetch(1,expected_generation=generation,deadline_monotonic=time.monotonic()+.1)
        except BrokerError as exc: errors.append(exc)
        finally: done.set()
    thread=threading.Thread(target=worker); thread.start()
    try:
        assert lock_held.wait(5)
        assert done.wait(.5), 'Actual Market.call lifecycle lock exceeded request deadline'
        assert errors and 'deadline' in str(errors[0])
    finally:
        release.set(); holder_thread.join(5); thread.join(5)
    market.get_session(1).broker._sdk.assert_not_called()


def test_actual_401_invalidation_lock_wait_respects_deadline(setup,monkeypatch):
    market,store,_=setup; monkeypatch.undo()
    response_ready=threading.Event(); lock_held=threading.Event(); release=threading.Event(); done=threading.Event(); errors=[]
    def response():
        response_ready.set(); assert lock_held.wait(5); return {'stCode':'401'}
    market.get_session(1).broker._sdk.return_value.holdings.side_effect=response
    market.last_request=0
    generation=market.session_generation(1)
    def holder():
        assert response_ready.wait(5)
        with market.lock:
            lock_held.set(); assert release.wait(5)
    holder_thread=threading.Thread(target=holder); holder_thread.start()
    def worker():
        try: PortfolioSnapshotService(market,store).fetch(1,expected_generation=generation,deadline_monotonic=time.monotonic()+.1)
        except BrokerError as exc: errors.append(exc)
        finally: done.set()
    thread=threading.Thread(target=worker); thread.start()
    try:
        assert lock_held.wait(5)
        assert done.wait(.5), 'Actual 401 invalidation lock exceeded request deadline'
        assert errors and 'deadline' in str(errors[0])
    finally:
        release.set(); holder_thread.join(5); thread.join(5)
    assert market.get_session(1).portfolio_cache is None

def test_final_review_semantic_strings_remain_exact(setup,monkeypatch):
    from decimal import Decimal
    market,_,_=setup; original=market.call
    quantity='0.'+'0'*158+'1'
    symbol='X'*500
    def call(method,user_id):
        if method=='holdings': return {'data':[{'quantity':quantity,'exchangeSegment':'nse_cm','displaySymbol':symbol}]}
        if method=='order_report': return {'data':[{'qty':'1','trdSym':symbol,'nOrdNo':'9'*500}]}
        return original(method,user_id)
    monkeypatch.setattr(market,'call',call)
    result=fetch(setup)
    assert result.sections['holdings'].rows[0].quantity==Decimal(quantity)
    assert result.sections['holdings'].rows[0].symbol==symbol
    assert result.sections['orders'].rows[0].order_id=='9'*500


def test_final_review_source_time_and_cache_keep_earliest_start(setup):
    a=fetch(setup); b=fetch(setup)
    earliest=min(s.retrieval_started_at for s in a.sections.values())
    assert a.source_observed_at==b.source_observed_at==earliest
    assert a.sections==b.sections
