import asyncio
from datetime import UTC,datetime,timedelta
from unittest.mock import patch

from app.terminal.analytics_capture import AnalyticsCaptureService
from app.terminal.analytics_runtime import TurnBudget
from app.terminal.analytics_sources import ParticipantReports
from app.terminal.options_snapshot import OptionsContext
from test_analytics_capture import sources


def report():
    day = (datetime.now(UTC)-timedelta(days=1)).date()
    csv = f'Participant wise Open Interest as on {day:%d-%b-%Y}\nClient Type,Future Index Long,Future Index Short,Option Index Call Long,Option Index Call Short,Option Index Put Long,Option Index Put Short\nFII,75,25,10,30,40,10\nDII,0,0,0,0,0,0\nPro,1,2,3,4,5,6\nClient,8,2,80,20,10,20\n'
    return day,csv


def test_participant_import_is_captured_without_shared_cache_promotion(tmp_path):
    market,portfolio,snapshots,store = sources(tmp_path)
    day,csv = report()
    raw = dict(context=OptionsContext().model_dump(),observed_at=datetime.now(UTC),provenance='User report copy',licence='Personal',
        participant_report_date=day,participant_csv=csv)
    async def run():
        captured = await AnalyticsCaptureService(market,store,snapshots,portfolio).capture(7,OptionsContext(),
            ['get_participant_fii_dii_flow'],budget=TurnBudget(),historical_input=raw)
        item = captured.for_role('portfolio_analysis')['get_participant_fii_dii_flow']
        assert item.metrics['participants']['FII']['index_futures_long_share']==.75
        assert item.metrics['unit']=='contracts'
        assert item.metrics['report_date']==day.isoformat()
        assert item.coverage['input_provenance']=='user_declared_unverified'
        assert ParticipantReports(store).cached(day,_official=True) is None
        snapshots.fetch.assert_not_called()
    asyncio.run(run())


def test_official_and_imported_revisions_are_isolated(tmp_path):
    _,_,_,store = sources(tmp_path)
    day,csv = report()
    reports = ParticipantReports(store)
    imported = reports.import_report(day,csv)
    assert reports.cached(day,_official=True) is None
    official = reports.import_report(day,csv,_official_fetch=True)
    with patch('app.terminal.analytics_sources.httpx.Client',side_effect=AssertionError('Unexpected network')):
        assert reports.fetch(day)['provenance']=='official_https_fetch'
    assert imported['checksum']==official['checksum']
    assert reports.cached(day)['provenance']=='validated-import'


def test_official_source_outage_preserves_independent_options_evidence(tmp_path):
    import httpx
    market,portfolio,snapshots,store=sources(tmp_path)
    raw=dict(context=OptionsContext().model_dump(),observed_at=datetime.now(UTC),provenance='Official report request',licence='Personal',participant_report_date=report()[0])
    async def run():
        with patch.object(ParticipantReports,'fetch',side_effect=httpx.ReadTimeout('private transport detail')):
            captured=await AnalyticsCaptureService(market,store,snapshots,portfolio).capture(7,OptionsContext(),
                ['get_nse_oi_microstructure','get_participant_fii_dii_flow'],budget=TurnBudget(),historical_input=raw)
        assert captured.for_role('options_trading_analysis')['get_nse_oi_microstructure'].metrics['pcr_oi']==2
        item=captured.for_role('portfolio_analysis')['get_participant_fii_dii_flow']
        assert item.status=='UNAVAILABLE'
        assert item.unavailable_reasons['participant_report']=='official_participant_source_unavailable_or_invalid'
        assert 'private transport detail' not in item.model_dump_json()
    asyncio.run(run())


def test_six_declared_sessions_compute_changes_and_label_heuristic():
    from app.terminal.nse_participant_flow import participant_history_change
    day,csv = report()
    history = []
    for index in range(6):
        dated = day-timedelta(days=5-index)
        content = csv.replace(f'{day:%d-%b-%Y}',f'{dated:%d-%b-%Y}').replace('75,25',f'{75-index},{25+index}')
        history.append(ParticipantReports.parse_report(dated,content))
    result = participant_history_change(history[-1],history,sessions_complete=True,price_return=.01)
    assert result['five_day_change']['FII']['net_index_futures']==-10
    assert result['divergence_flag']['FII'] is True
    assert 'heuristic' in result['divergence_basis']
    assert participant_history_change(history[-1],history,sessions_complete=False)['five_day_change'] is None


def test_institutional_retail_positioning_heuristic_is_explicit():
    _,csv = report()
    csv = csv.replace('FII,75,25,10,30,40,10','FII,75,25,1,99,99,1').replace('Pro,1,2,3,4,5,6','Pro,1,2,1,99,99,1')
    parsed = ParticipantReports.parse_report(report()[0],csv)
    assert parsed['institutional_retail_divergence_flag']=='BEARISH_INSTITUTIONAL_DIVERGENCE'
    assert parsed['unit']=='contracts'
