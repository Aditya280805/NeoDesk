"""Explicit, dry-run-first risk report maintenance.

python -m app.terminal.portfolio_risk_maintenance --database PATH --older-than-days 90 [--apply]
"""
import argparse
from pathlib import Path
from .store import Store
from .portfolio_risk_store import PortfolioRiskStore

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',type=Path,required=True)
    parser.add_argument('--older-than-days',type=int,required=True)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    if args.older_than_days<1: parser.error('--older-than-days must be positive')
    if not args.database.is_file(): parser.error('database must already exist')
    # Do not initialize unrelated tables or accounts during maintenance.
    store=object.__new__(Store)
    store.path=args.database
    risk=object.__new__(PortfolioRiskStore)
    risk.store=store
    rows=risk.prune_reports(args.older_than_days,apply=args.apply)
    print(f'{"Deleted" if args.apply else "Would delete"} {len(rows)} unreferenced reports')

if __name__=='__main__': main()
