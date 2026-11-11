import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.terminal.analytics_runtime import TurnBudget
from app.terminal.analytics_store import AnalyticsStore
from app.terminal.options_snapshot import OptionsContext


def sources(tmp_path):
    market = SimpleNamespace(session_generation=Mock(return_value='session-7'),lock=threading.RLock())
    portfolio = Mock()
    portfolio.assert_generation = Mock(return_value=None)
    snapshots = Mock()
    snapshots.fetch.return_value = dict(snapshot_id='source-7',source='kotak',underlying='NIFTY',exchange='nse_fo',
        expiry='2026-11-17',exchange_timestamp=None,rows=[dict(side='CALL',strike=100,open_interest=10),dict(side='PUT',strike=100,open_interest=20)])
    store = AnalyticsStore(tmp_path/'capture.sqlite3')
    return market,portfolio,snapshots,store


def test_capture_collects_off_loop_once_and_persists_owner_evidence(tmp_path):
    from app.terminal.analytics_capture import AnalyticsCaptureService
    market,portfolio,snapshots,store = sources(tmp_path)
    owner_thread = threading.get_ident()
    original = snapshots.fetch.return_value
    def fetch(*args):
        assert threading.get_ident()!=owner_thread
        return original
    snapshots.fetch.side_effect = fetch
    async def scenario():
        service = AnalyticsCaptureService(market,store,snapshots,portfolio)
        result = await service.capture(7,OptionsContext(expiry='2026-11-17'),
            ['get_nse_oi_microstructure','get_vol_surface_and_greeks'],budget=TurnBudget())
        evidence = result.for_role('options_trading_analysis')
        oi = evidence['get_nse_oi_microstructure']
        assert oi.metrics['pcr_oi']==2
        assert evidence['get_vol_surface_and_greeks'].status=='UNAVAILABLE'
        assert snapshots.fetch.call_count==1
        assert result.session_generation=='session-7'
        assert not result.for_role('portfolio_risk')
        assert store.read(7,str(oi.evidence_id))['metrics']['pcr_oi']==2
        assert store.read(8,str(oi.evidence_id)) is None
    asyncio.run(scenario())


def test_capture_rejects_demo_or_contradictory_context(tmp_path):
    from app.terminal.analytics_capture import AnalyticsCaptureService
    for invalid in ({'source':'demo'},{'underlying':'OTHER'}):
        market,portfolio,snapshots,store = sources(tmp_path)
        snapshots.fetch.return_value.update(invalid)
        async def scenario():
            with pytest.raises(ValueError):
                await AnalyticsCaptureService(market,store,snapshots,portfolio).capture(7,OptionsContext(),['get_nse_oi_microstructure'],budget=TurnBudget())
        asyncio.run(scenario())


def test_session_change_publishes_no_evidence(tmp_path):
    from app.terminal.analytics_capture import AnalyticsCaptureService
    market,portfolio,snapshots,store = sources(tmp_path)
    market.session_generation.side_effect = ['session-7','session-new']
    async def scenario():
        with pytest.raises(ValueError):
            await AnalyticsCaptureService(market,store,snapshots,portfolio).capture(7,OptionsContext(),['get_nse_oi_microstructure'],budget=TurnBudget())
    asyncio.run(scenario())
    with store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM analytics_evidence').fetchone()[0]==0


def test_capture_never_defaults_owner_or_accepts_unknown_tools(tmp_path):
    from app.terminal.analytics_capture import AnalyticsCaptureService
    market,portfolio,snapshots,store = sources(tmp_path)
    async def scenario():
        service = AnalyticsCaptureService(market,store,snapshots,portfolio)
        for owner,names in ((None,['get_nse_oi_microstructure']),(True,['get_nse_oi_microstructure']),(7,['place_order'])):
            with pytest.raises(ValueError):
                await service.capture(owner,OptionsContext(),names,budget=TurnBudget())
        assert not snapshots.fetch.called
    asyncio.run(scenario())


def test_cancelled_capture_retains_shared_capacity_and_does_not_publish(tmp_path):
    from app.terminal.analytics_capture import AnalyticsCaptureService
    from app.terminal.analytics_runtime import BoundedWork
    market,portfolio,snapshots,store = sources(tmp_path)
    entered,release = threading.Event(),threading.Event()
    raw = snapshots.fetch.return_value
    def slow(*args):
        entered.set()
        release.wait(3)
        return raw
    snapshots.fetch.side_effect = slow
    async def scenario():
        shared = {}
        service = AnalyticsCaptureService(market,store,snapshots,portfolio,work=BoundedWork(pending=shared))
        task = asyncio.create_task(service.capture(7,OptionsContext(),['get_nse_oi_microstructure'],budget=TurnBudget()))
        try:
            async with asyncio.timeout(2):
                while not entered.is_set():
                    await asyncio.sleep(.001)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert 7 in shared
            with pytest.raises(ValueError):
                await service.capture(7,OptionsContext(),['get_nse_oi_microstructure'],budget=TurnBudget())
        finally:
            release.set()
            await asyncio.gather(*shared.values(),return_exceptions=True)
        assert not shared
    asyncio.run(scenario())
    with store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM analytics_evidence').fetchone()[0]==0


@pytest.mark.parametrize('change',['cancel','session'])
def test_blocked_publication_revalidates_before_commit(tmp_path,change):
    from app.terminal.analytics_capture import AnalyticsCaptureService
    market,portfolio,snapshots,store = sources(tmp_path)
    entered,release = threading.Event(),threading.Event()
    publish = store.capture_batch
    def blocked(*args,**kwargs):
        entered.set()
        release.wait(3)
        return publish(*args,**kwargs)
    store.capture_batch = blocked
    async def scenario():
        service = AnalyticsCaptureService(market,store,snapshots,portfolio)
        task = asyncio.create_task(service.capture(7,OptionsContext(),['get_nse_oi_microstructure'],budget=TurnBudget()))
        try:
            async with asyncio.timeout(2):
                while not entered.is_set():
                    await asyncio.sleep(.001)
            if change=='cancel':
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            else:
                market.session_generation.return_value='new-session'
            release.set()
            if change=='session':
                with pytest.raises(ValueError):
                    await task
            await asyncio.gather(*service.work.pending.values(),return_exceptions=True)
        finally:
            release.set()
            await asyncio.gather(task,return_exceptions=True)
    asyncio.run(scenario())
    with store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM analytics_evidence').fetchone()[0]==0


def test_capture_keeps_real_normalizer_identity_caveats(tmp_path):
    from app.terminal.analytics_capture import AnalyticsCaptureService
    from app.terminal.options_snapshot import normalize_snapshot
    market,portfolio,snapshots,store = sources(tmp_path)
    def leg(side):
        return dict(instrument={'symbol':side,'strikePrice':100},quote={'ltp':2,'volume':10},openInterest={'current':10})
    snapshots.fetch.return_value = normalize_snapshot({'common_data':{'mktLot':25},'call':[leg('CALL')],'put':[leg('PUT')]},OptionsContext())
    async def scenario():
        captured = await AnalyticsCaptureService(market,store,snapshots,portfolio).capture(7,OptionsContext(),['get_nse_oi_microstructure'],budget=TurnBudget())
        item = captured.for_role('options_trading_analysis')['get_nse_oi_microstructure']
        assert item.coverage['market_identity']['underlying'] is False
        assert item.unavailable_reasons['market_identity']=='provider_identity_unverified'
        assert any('identity' in text.lower() for text in item.limitations)
        assert item.status=='PARTIAL'
    asyncio.run(scenario())


def test_atomic_capture_batch_rolls_back_after_precommit_invalidity(tmp_path):
    from datetime import UTC,datetime
    from app.terminal.analytics_contracts import AnalyticsEvidence
    store = AnalyticsStore(tmp_path/'atomic.sqlite3')
    item = AnalyticsEvidence(calculation_version='test.1',observed_at=None,retrieved_at=datetime.now(UTC),status='AVAILABLE',metrics={'x':1})
    calls = []
    def validate():
        calls.append(1)
        if len(calls)==2:
            raise ValueError('session changed')
    with pytest.raises(ValueError):
        store.capture_batch(7,[item],validate=validate)
    assert store.read(7,str(item.evidence_id)) is None
