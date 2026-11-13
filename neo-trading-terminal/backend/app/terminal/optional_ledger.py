"""Canonical optional ledger CSV; raw text stays in owner-scoped import storage."""
import csv
import io
import re
from datetime import date

def summarize_ledger(text):
    if len(text.encode('utf-8'))>1048576: raise ValueError('Ledger exceeds one MiB')
    reader=csv.DictReader(io.StringIO(text.lstrip('\ufeff')),strict=True)
    if reader.fieldnames!=['date','type','amount_paise']: raise ValueError('Expected date,type,amount_paise columns')
    totals={key:0 for key in ('DEPOSIT','WITHDRAWAL','CHARGE','SETTLEMENT_CREDIT','SETTLEMENT_DEBIT')}
    count,previous=0,None
    try:
        records=list(reader)
    except csv.Error:
        raise ValueError('Malformed ledger CSV') from None
    for row in records:
        count+=1
        if count>10000 or None in row or None in row.values(): raise ValueError('Invalid bounded ledger rows')
        day=date.fromisoformat(row['date'])
        if previous and day<previous: raise ValueError('Ledger dates must be ordered')
        previous=day
        if row['type'] not in totals or not re.fullmatch(r'0|[1-9][0-9]{0,15}',row['amount_paise']): raise ValueError('Invalid ledger type or integer paise')
        totals[row['type']]+=int(row['amount_paise'])
        if sum(totals.values())>9007199254740991: raise ValueError('Ledger exceeds exact paise range')
    if not count: raise ValueError('Ledger contains no transactions')
    return dict(transaction_count=count,totals_paise=totals,net_external_flow_paise=totals['DEPOSIT']-totals['WITHDRAWAL'],
        performance_return=None,provenance='user_uploaded_unverified',complete_account_coverage=False,
        limitation='Cash movements only; returns need aligned valuations and complete period coverage. Ledger is optional for market analysis.')
