"""Canonical analytics router replay; model evaluation requires explicit live mode."""
import argparse
import asyncio
import json
from pathlib import Path

from .analytics_contracts import RoutingDecision
from .analytics_runtime import TurnBudget


def fixtures():
    return json.loads((Path(__file__).resolve().parents[2]/'evals'/'analytics_router.v1.json').read_text(encoding='utf-8'))


async def evaluate(*,live=False,config=None):
    results = []
    for case in fixtures():
        expected = RoutingDecision(mode=case['mode'],delegated_agents=case['roles'])
        try:
            if live:
                from .analytics_coordinator import classify
                actual = await classify(config,case['question'],TurnBudget())
            else:
                # Protocol replay of a golden structured reply, not text classification.
                actual = RoutingDecision.model_validate_json(expected.model_dump_json())
            passed = actual.mode==expected.mode and actual.delegated_agents==expected.delegated_agents
            results.append(dict(id=case['id'],passed=passed,actual_mode=actual.mode))
        except Exception:
            results.append(dict(id=case['id'],passed=False,failure='classification_or_contract_failed'))
    return dict(suite='analytics-router.1',mode='live-model' if live else 'offline-contract-replay',model_evaluated=live,
        total=len(results),passed=sum(case['passed'] for case in results),results=results)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode',choices=('offline','live-model'),default='offline')
    args = parser.parse_args()
    config = None
    if args.mode=='live-model':
        from app.core.config import Settings
        config = Settings()
    report = asyncio.run(evaluate(live=args.mode=='live-model',config=config))
    print(json.dumps(report,allow_nan=False))
    return 0 if report['passed']==report['total'] else 1


if __name__=='__main__':
    raise SystemExit(main())
