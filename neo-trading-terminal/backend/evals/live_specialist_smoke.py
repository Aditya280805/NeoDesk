"""Explicit live-model smoke against isolated synthetic sources, never broker data."""
import argparse
import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path


async def run():
    # Dev harness dependency only; do not mount this script in application APIs.
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests'))
    from test_analytics_capture import sources
    from app.core.config import Settings
    from app.terminal.analytics_capture import AnalyticsCaptureService
    from app.terminal.analytics_runtime import TurnBudget
    from app.terminal.analytics_stage import run_specialist_stage
    from app.terminal.options_mcp import OptionsMCP
    from app.terminal.options_snapshot import OptionsContext
    with tempfile.TemporaryDirectory(prefix='neodesk-live-stage-') as folder:
        market,portfolio,snapshots,store=sources(Path(folder))
        captured=await AnalyticsCaptureService(market,store,snapshots,portfolio).capture(7,OptionsContext(),
            ['get_nse_oi_microstructure'],budget=TurnBudget())
        runtime=OptionsMCP(snapshots,port=0,portfolio_service=portfolio)
        budget=TurnBudget()
        started=time.monotonic()
        report=dict(model_evaluated=True,broker_evaluated=False,source='isolated_synthetic_fixture')
        try:
            async with runtime.lifespan():
                result=await run_specialist_stage(Settings(),runtime,captured,7,'options_trading_analysis',
                    'Explain the supplied synthetic option-chain evidence and its coverage.',
                    ['get_nse_oi_microstructure'],budget)
            report.update(status=result['status'],claims=len(result['claims']))
        except Exception as error:
            report.update(error_type=type(error).__name__)
        report.update(mcp_reads=budget.calls.get('options_trading_analysis',0),
            elapsed_seconds=round(time.monotonic()-started,3),capabilities_released=not runtime.capabilities)
        report['passed']=report.get('status')=='completed' and report['mcp_reads']==1 and report['capabilities_released']
        return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live-model',action='store_true',help='Explicitly authorize this command to invoke the configured model.')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if not args.live_model:
        parser.error('--live-model is required; this is not an offline replay.')
    report=asyncio.run(run())
    if args.output is not None:
        args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report))
    return 0 if report['passed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
