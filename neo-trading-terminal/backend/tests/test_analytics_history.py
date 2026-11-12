import asyncio
from datetime import UTC,datetime,timedelta
from unittest.mock import Mock
from zoneinfo import ZoneInfo

from app.terminal.market import parse_master
from app.terminal.analytics_capture import AnalyticsCaptureService
from app.terminal.analytics_runtime import TurnBudget
from app.terminal.options_snapshot import OptionsContext
from test_analytics_capture import sources


def setup(tmp_path):
    market,portfolio,snapshots,store = sources(tmp_path)
    catalogue = Mock()
    rows = parse_master('pSymbol,pTrdSymbol,pSymbolName,pExchSeg,pInstType,pGroup,pISIN\n26000,NIFTY,NIFTY,nse_cm,,,\n','nse_cm')
    catalogue.search.return_value={'items':rows,'total':1}
    end = datetime.now(UTC).astimezone(ZoneInfo('Asia/Kolkata')).date()-timedelta(days=1)
    candles = [[f'{end-timedelta(days=39-i)}T15:30:00+05:30',100+i,102+i,99+i,101+i,1000,None] for i in range(40)]
    market.call=Mock(return_value={'interval':'D','data':{'candles':candles}})
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
        assert market.call.call_count==1
        assert market.call.call_args.args==('historical_data',)
        assert market.call.call_args.kwargs['neosymbol']=='nse_cm|26000'
    asyncio.run(run())


def test_malformed_history_is_not_repaired_or_used(tmp_path):
    market,portfolio,snapshots,store,catalogue = setup(tmp_path)
    market.call.return_value['data']['candles'][0][2]=1
    async def run():
        captured = await AnalyticsCaptureService(market,store,snapshots,portfolio,catalogue=catalogue).capture(7,OptionsContext(),
            ['get_technical_regime_snapshot'],budget=TurnBudget())
        item = captured.for_role('options_trading_analysis')['get_technical_regime_snapshot']
        assert item.status=='UNAVAILABLE'
        assert item.unavailable_reasons['bars']=='broker_daily_history_invalid_or_unavailable'
    asyncio.run(run())
