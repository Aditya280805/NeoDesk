"""Documented day-only broker fills, projected to non-identifying summary."""
from datetime import datetime
from decimal import Decimal,InvalidOperation
from .portfolio_source_diagnostics import documented_empty

def parse_daily_fills(raw,trade_date):
    rows = [] if documented_empty(raw) else raw.get('data') if isinstance(raw,dict) else None
    if not isinstance(rows,list) or len(rows)>1000:
        raise ValueError('Invalid bounded daily fill envelope')
    seen, buys, sells = set(),Decimal(0),Decimal(0)
    for row in rows:
        if not isinstance(row,dict): raise ValueError('Invalid fill')
        identifier=(row.get('exSeg'),row.get('flId'),row.get('flLeg'))
        if not row.get('flId') or identifier in seen:
            raise ValueError('Missing or duplicate fill identity')
        seen.add(identifier)
        when=datetime.strptime(row['flDt']+' '+row['flTm'],'%d-%b-%Y %H:%M:%S')
        if when.date()!=trade_date or row.get('exSeg') not in ('nse_cm','bse_cm','nse_fo','bse_fo'):
            raise ValueError('Fill date or exchange differs from request')
        try:
            qty,price=Decimal(str(row.get('fldQty'))),Decimal(str(row.get('avgPrc')))
        except InvalidOperation:
            raise ValueError('Invalid fill numeric fields') from None
        if not qty.is_finite() or qty<=0 or qty!=qty.to_integral_value() or not price.is_finite() or price<=0:
            raise ValueError('Invalid fill quantity or price')
        value=qty*price*100
        if value!=value.to_integral_value() or value>9007199254740991:
            raise ValueError('Fill turnover exceeds exact paise contract')
        if row.get('trnsTp')=='B': buys+=value
        elif row.get('trnsTp')=='S': sells+=value
        else: raise ValueError('Unknown fill side')
    if max(buys,sells)>9007199254740991: raise ValueError('Aggregate turnover exceeds paise contract')
    return dict(trade_date=trade_date.isoformat(),fill_count=len(rows),buy_turnover_paise=int(buys),
        sell_turnover_paise=int(sells),fees_paise=None,complete_account_history=False,
        scope='broker_current_day_fills_only',cash_flow_history=None,
        limitations=['Trade turnover is not profit or external cash flow. Opening inventory, fees, cash ledger and adjusted history are not supplied by this report.'])
