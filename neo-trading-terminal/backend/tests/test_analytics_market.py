import asyncio
from datetime import UTC,datetime
from unittest.mock import Mock
from uuid import uuid4

import pytest

from app.terminal.analytics_capture import AnalyticsCaptureService
from app.terminal.analytics_runtime import TurnBudget
from app.terminal.options_snapshot import OptionsContext
from test_analytics_capture import sources


def setup(tmp_path):
    market,portfolio,snapshots,store = sources(tmp_path)
    chain = snapshots.fetch.return_value
    chain.update(snapshot_id=str(uuid4()),retrieved_at=datetime.now(UTC).isoformat())
    for row in chain['rows']: row.update(symbol=row['side'],ltp=2)
    catalogue = Mock()
    catalogue.search.return_value = {'items':[dict(id='nse_fo|1',token='1',symbol='CALL',exchange='nse_fo',kind='OPTION',expiry='2026-11-17',strike=100,option_type='CE',source_metadata={'source':'kotak-scrip-master','lLotSize':'25'})]}
    market.call = Mock(return_value=[dict(exchange='nse_fo',exchange_token='1',ltp='2',depth={'buy':[dict(price='1.9',quantity='25')],'sell':[dict(price='2.1',quantity='25')]})])
    return market,portfolio,snapshots,store,catalogue


def test_capture_depth_once_without_promoting_identity_or_proposals(tmp_path):
    market,portfolio,snapshots,store,catalogue = setup(tmp_path)
    async def run():
        captured = await AnalyticsCaptureService(market,store,snapshots,portfolio,catalogue=catalogue).capture(
            7,OptionsContext(expiry='2026-11-17'),['get_nse_oi_microstructure'],budget=TurnBudget())
        item = captured.for_role('options_trading_analysis')['get_nse_oi_microstructure']
        depth = item.metrics['broker_quote_depth']
        assert depth['quotes'][0]['bid']=='1.9' and depth['quotes'][0]['ask']=='2.1'
        assert depth['contracts'][0]['identity_verified'] is False
        assert depth['contracts'][0]['underlying_id'] is None
        assert not item.candidate_proposals
        assert item.coverage['quote_depth']['exchange_timestamp_verified'] is False
        assert snapshots.fetch.call_count==1 and market.call.call_count==1
        kwargs = market.call.call_args.kwargs
        assert kwargs['user_id']==7 and kwargs['deadline_monotonic']>0
    asyncio.run(run())


def test_wrong_quote_token_rejects_whole_capture(tmp_path):
    market,portfolio,snapshots,store,catalogue = setup(tmp_path)
    market.call.return_value[0]['exchange_token']='other'
    with pytest.raises(ValueError):
        asyncio.run(AnalyticsCaptureService(market,store,snapshots,portfolio,catalogue=catalogue).capture(
            7,OptionsContext(),['get_nse_oi_microstructure'],budget=TurnBudget()))
    with store.connect() as db:
        assert db.execute('SELECT count(*) FROM analytics_evidence').fetchone()[0]==0


def test_generation_change_during_quote_fetch_prevents_publication(tmp_path):
    market,portfolio,snapshots,store,catalogue = setup(tmp_path)
    rows = market.call.return_value
    def change(*args,**kwargs):
        market.session_generation.return_value='different-session'
        return rows
    market.call.side_effect=change
    with pytest.raises(ValueError):
        asyncio.run(AnalyticsCaptureService(market,store,snapshots,portfolio,catalogue=catalogue).capture(
            7,OptionsContext(),['get_nse_oi_microstructure'],budget=TurnBudget()))
    with store.connect() as db:
        assert db.execute('SELECT count(*) FROM analytics_evidence').fetchone()[0]==0


def test_quote_failure_preserves_oi_with_sanitized_missing_depth(tmp_path):
    from app.brokers.base_broker import BrokerError
    market,portfolio,snapshots,store,catalogue = setup(tmp_path)
    market.call.side_effect=BrokerError('sensitive-provider-detail')
    async def run():
        result = await AnalyticsCaptureService(market,store,snapshots,portfolio,catalogue=catalogue).capture(
            7,OptionsContext(),['get_nse_oi_microstructure'],budget=TurnBudget())
        item = result.for_role('options_trading_analysis')['get_nse_oi_microstructure']
        assert item.metrics['pcr_oi']==2
        assert item.unavailable_reasons['quote_depth']=='broker_quote_depth_unavailable'
        assert 'sensitive-provider-detail' not in item.model_dump_json()
    asyncio.run(run())


def test_empty_quote_batch_is_not_reported_as_available_depth(tmp_path):
    market,portfolio,snapshots,store,catalogue = setup(tmp_path)
    market.call.return_value=[]
    async def run():
        captured = await AnalyticsCaptureService(market,store,snapshots,portfolio,catalogue=catalogue).capture(
            7,OptionsContext(),['get_nse_oi_microstructure'],budget=TurnBudget())
        item = captured.for_role('options_trading_analysis')['get_nse_oi_microstructure']
        assert item.coverage['quote_depth']['reported_bid_ask_pairs']==0
        assert item.unavailable_reasons['quote_depth']=='broker_returned_no_bid_ask_pairs'
        assert item.metrics['pcr_oi']==2
    asyncio.run(run())


def test_surface_without_pricing_is_partial_when_depth_is_present(tmp_path):
    market,portfolio,snapshots,store,catalogue = setup(tmp_path)
    async def run():
        captured = await AnalyticsCaptureService(market,store,snapshots,portfolio,catalogue=catalogue).capture(
            7,OptionsContext(),['get_vol_surface_and_greeks'],budget=TurnBudget())
        item = captured.for_role('options_trading_analysis')['get_vol_surface_and_greeks']
        assert item.status=='PARTIAL'
        assert 'surface_rows' in item.unavailable_reasons
        assert item.metrics['broker_quote_depth']['quotes'][0]['bid']=='1.9'
    asyncio.run(run())
