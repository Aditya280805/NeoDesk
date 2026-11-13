"""Canonical analytics router replay; model evaluation requires explicit live mode."""
import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

from .analytics_contracts import RoutingDecision
from .analytics_runtime import TurnBudget


def fixtures(dataset='canonical'):
    names={'canonical':'analytics_router.v1.json','heldout':'analytics_router_heldout.v1.json'}
    return json.loads((Path(__file__).resolve().parents[2]/'evals'/names[dataset]).read_text(encoding='utf-8'))


async def evaluate(*,live=False,config=None,on_result=None,dataset='canonical'):
    results = []
    for case in fixtures(dataset):
        expected = RoutingDecision(mode=case['mode'],delegated_agents=case['roles'])
        started=time.monotonic()
        try:
            if live:
                from .analytics_coordinator import classify
                actual = await classify(config,case['question'],TurnBudget())
            else:
                # Protocol replay of a golden structured reply, not text classification.
                actual = RoutingDecision.model_validate_json(expected.model_dump_json())
            passed = actual.mode==expected.mode and actual.delegated_agents==expected.delegated_agents
            results.append(dict(id=case['id'],passed=passed,actual_mode=actual.mode,actual_roles=list(actual.delegated_agents)))
        except Exception as error:
            results.append(dict(id=case['id'],passed=False,failure='classification_or_contract_failed',error_type=type(error).__name__))
        results[-1]['elapsed_seconds']=round(time.monotonic()-started,3)
        if on_result is not None:
            on_result(results[-1])
    metadata={}
    if live:
        from .options_model import provider_settings
        provider=provider_settings(config)
        metadata=dict(provider=provider.provider,model=provider.model)
    return dict(suite='analytics-router.1',dataset=dataset,router_version='analytics-coordinator.2',mode='live-model' if live else 'offline-contract-replay',model_evaluated=live,**metadata,
        total=len(results),passed=sum(case['passed'] for case in results),results=results)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode',choices=('offline','live-model'),default='offline')
    parser.add_argument('--output',type=Path,help='Write a sanitized reproducible JSON report.')
    parser.add_argument('--progress',action='store_true',help='Print per-case summaries to stderr.')
    parser.add_argument('--dataset',choices=('canonical','heldout'),default='canonical')
    args = parser.parse_args()
    config = None
    if args.mode=='live-model':
        from app.core.config import Settings
        config = Settings()
    report = asyncio.run(evaluate(live=args.mode=='live-model',config=config,dataset=args.dataset,
        on_result=(lambda row:print(json.dumps(row),file=sys.stderr,flush=True)) if args.progress else None))
    if args.output is not None:
        args.output.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(report,allow_nan=False))
    return 0 if report['passed']==report['total'] else 1


if __name__=='__main__':
    raise SystemExit(main())
