import asyncio
from datetime import UTC,datetime,timedelta
from unittest.mock import Mock
from zoneinfo import ZoneInfo

from app.terminal.market import parse_master
from app.terminal.analytics_capture import AnalyticsCaptureService
from app.terminal.analytics_runtime import TurnBudget
from app.terminal.options_snapshot import OptionsContext
from test_analytics_capture import sources


def test_bounded_history_warms_long_indicators_without_overlapping_batches(tmp_path):
    from app.terminal.analytics_history import technical_history
    market,_,_,_,catalogue = setup(tmp_path)
    def history(method, **kwargs):
        start = datetime.fromisoformat(kwargs['from_date']).date()
        end = datetime.fromisoformat(kwargs['to_date']).date()
        assert (end-start).days < 180
        candles = []
        day = start
        while day <= end:
            if day.weekday() < 5:
                candles.append([f'{day}T15:30:00+05:30',100,102,99,101,1000])
            day += timedelta(days=1)
        return {'data':{'candles':candles}}
    market.call.side_effect = history
    result = technical_history(market,catalogue,7,OptionsContext(),999999999,lambda:None)
    dates = [bar['time'] for bar in result['bars']]
    assert len(dates) >= 200
    assert dates == sorted(set(dates))
    assert market.call.call_count <= 3


def setup(tmp_path):
    market,portfolio,snapshots,store = sources(tmp_path)
    catalogue = Mock()
    rows = parse_master('pSymbol,pTrdSymbol,pSymbolName,pExchSeg,pInstType,pGroup,pISIN\n26000,NIFTY,NIFTY,nse_cm,,,\n','nse_cm')
    catalogue.search.return_value={'items':rows,'total':1}
    end = datetime.now(UTC).astimezone(ZoneInfo('Asia/Kolkata')).date()-timedelta(days=1)
    candles = [[f'{end-timedelta(days=39-i)}T15:30:00+05:30',100+i,102+i,99+i,101+i,1000,None] for i in range(40)]
    market.call=Mock(side_effect=lambda *args,**kw: {'interval':'D','data':{'candles':[
        row for row in candles if kw['from_date'] <= row[0][:10] <= kw['to_date']]}})
    return market,portfolio,snapshots,store,catalogue


def test_capture_strict_daily_history_without_invented_intraday_vwap(tmp_path):
    market,portfolio,snapshots,store,catalogue = setup(tmp_path)
    async def run():
        captured = await AnalyticsCaptureService(market,store,snapshots,portfolio,catalogue=catalogue).capture(7,OptionsContext(),
            ['get_technical_regime_snapshot'],budget=TurnBudget())
        item = captured.for_role('options_trading_analysis')['get_technical_regime_snapshot']
        assert item.metrics['ema20'] is not None
        assert item.metrics['ema200'] is None and item.metrics['vwap'] is None
        assert item.coverage['source_semantics']=='historical_closed_bars'
        assert market.call.call_count==2
        assert market.call.call_args.args==('historical_data',)
        assert market.call.call_args.kwargs['neosymbol']=='nse_cm|26000'
    asyncio.run(run())


def test_malformed_history_is_not_repaired_or_used(tmp_path):
    market,portfolio,snapshots,store,catalogue = setup(tmp_path)
    market.call.side_effect=lambda *args,**kw: {'data':{'candles':[[f'{kw["to_date"]}T15:30:00+05:30',100,1,99,101,1000]]}}
    async def run():
        captured = await AnalyticsCaptureService(market,store,snapshots,portfolio,catalogue=catalogue).capture(7,OptionsContext(),
            ['get_technical_regime_snapshot'],budget=TurnBudget())
        item = captured.for_role('options_trading_analysis')['get_technical_regime_snapshot']
        assert item.status=='UNAVAILABLE'
        assert item.unavailable_reasons['bars']=='broker_daily_history_invalid_or_unavailable'
    asyncio.run(run())


def test_older_history_cannot_repeat_newer_candles(tmp_path):
    import pytest
    from app.terminal.analytics_history import technical_history, HistorySourceUnavailable
    market,_,_,_,catalogue = setup(tmp_path)
    day = datetime.now(UTC).astimezone(ZoneInfo('Asia/Kolkata')).date()-timedelta(days=1)
    market.call.side_effect = None
    market.call.return_value = {'data':{'candles':[[f'{day}T15:30:00+05:30',100,102,99,101,1000]]}}
    with pytest.raises(HistorySourceUnavailable):
        technical_history(market,catalogue,7,OptionsContext(),999999999,lambda:None)


def test_history_rechecks_session_before_older_batch(tmp_path):
    import pytest
    from app.terminal.analytics_history import technical_history
    market,_,_,_,catalogue = setup(tmp_path)
    checks = 0
    def validate():
        nonlocal checks
        checks += 1
        if checks == 3:
            raise PermissionError('Session changed')
    with pytest.raises(PermissionError):
        technical_history(market,catalogue,7,OptionsContext(),999999999,validate)
    assert market.call.call_count == 1
