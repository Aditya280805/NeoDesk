"""Canonical optional ledger CSV; raw text stays in owner-scoped import storage."""
import csv
import io
import re
from datetime import date,datetime
from decimal import Decimal,InvalidOperation
from pydantic import BaseModel,ConfigDict,Field
from typing import Literal

class LedgerMapping(BaseModel):
    model_config=ConfigDict(extra='forbid')
    date_column:str=Field(default='date',min_length=1,max_length=100)
    type_column:str=Field(default='type',min_length=1,max_length=100)
    amount_column:str=Field(default='amount_paise',min_length=1,max_length=100)
    debit_column:str|None=Field(default=None,min_length=1,max_length=100)
    credit_column:str|None=Field(default=None,min_length=1,max_length=100)
    unit:Literal['INR','PAISE']='PAISE'
    date_format:Literal['%Y-%m-%d','%d/%m/%Y','%d-%m-%Y']='%Y-%m-%d'
    type_values:dict[str,str]=Field(default_factory=dict,max_length=50)

def normalize_ledger_csv(text,mapping):
    mapping=LedgerMapping.model_validate(mapping)
    if len(text.encode('utf-8'))>1048576: raise ValueError('Ledger exceeds one MiB')
    reader=csv.DictReader(io.StringIO(text.lstrip('\ufeff')),strict=True)
    if bool(mapping.debit_column)!=bool(mapping.credit_column): raise ValueError('Both debit and credit columns required')
    split=mapping.debit_column is not None
    columns=[mapping.date_column,mapping.type_column]+([mapping.debit_column,mapping.credit_column] if split else [mapping.amount_column])
    if len(set(columns))!=len(columns) or not reader.fieldnames or len(reader.fieldnames)!=len(set(reader.fieldnames)) or not set(columns)<=set(reader.fieldnames):
        raise ValueError('Unique mapped columns must exist in CSV header')
    out=io.StringIO()
    writer=csv.writer(out,lineterminator='\n')
    writer.writerow(['date','type','amount_paise'])
    try:
        for index,row in enumerate(reader):
            if index>=10000 or None in row or None in row.values(): raise ValueError('Invalid bounded ledger row')
            day=datetime.strptime(row[mapping.date_column],mapping.date_format).date()
            label=row[mapping.type_column]
            transaction=mapping.type_values.get(label,label)
            if split:
                debit=Decimal(row[mapping.debit_column].strip() or '0')
                credit=Decimal(row[mapping.credit_column].strip() or '0')
                if not debit.is_finite() or not credit.is_finite() or debit<0 or credit<0 or (debit>0)==(credit>0):
                    raise ValueError('Exactly one positive debit or credit required')
                is_credit=transaction in ('DEPOSIT','SETTLEMENT_CREDIT')
                if is_credit!=(credit>0): raise ValueError('Transaction label conflicts with debit/credit direction')
                value=credit if is_credit else debit
            else:
                value=Decimal(row[mapping.amount_column])
            paise=value*(100 if mapping.unit=='INR' else 1)
            if not paise.is_finite() or paise<0 or paise!=paise.to_integral_value() or paise>9007199254740991: raise ValueError('Amount must be nonnegative exact paise')
            writer.writerow([day.isoformat(),transaction,str(int(paise))])
    except (csv.Error,InvalidOperation,KeyError,TypeError):
        raise ValueError('Malformed mapped ledger') from None
    canonical=out.getvalue()
    summarize_ledger(canonical)
    return canonical

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
