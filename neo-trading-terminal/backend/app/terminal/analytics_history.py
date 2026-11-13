"""Bounded daily history acquisition; never repairs malformed OHLC."""
from datetime import UTC,datetime,timedelta
from zoneinfo import ZoneInfo

from .analytics_inputs import HistoricalBar

class HistorySourceUnavailable(ValueError):
    pass


def technical_history(market,catalogue,user,context,deadline,validate):
    if context.exchange!='nse_fo':
        return None
    rows = catalogue.search(query=context.underlying,exchange='nse_cm',kind='',limit=5000)
    if rows.get('total',len(rows['items']))>5000:
        return None
    matches = []
    for item in rows['items']:
        raw = item.get('identity_source_fields',{})
        if item.get('source_metadata',{}).get('source')!='kotak-scrip-master' or raw.get('pExchSeg')!='nse_cm' or raw.get('pSymbolName')!=context.underlying:
            continue
        if item.get('kind') not in ('INDEX','EQUITY','ETF') or item['kind']=='EQUITY' and raw.get('pGroup')!='EQ':
            continue
        if item.get('id')!='nse_cm|'+str(raw.get('pSymbol')):
            raise ValueError('Contradictory underlying master token')
        matches.append(item)
    if len(matches)!=1:
        return None
    end = datetime.now(UTC).astimezone(ZoneInfo('Asia/Kolkata')).date()-timedelta(days=1)
    final_end, combined = end, []
    for _ in range(3):
        start = end-timedelta(days=179)
        validate()
        raw = market.call('historical_data',user_id=user,neosymbol=matches[0]['id'],interval='D',
            from_date=start.isoformat(),to_date=end.isoformat(),deadline_monotonic=deadline)
        validate()
        try:
            # An explicitly empty older window establishes no additional history.
            if combined and isinstance(raw,dict) and raw.get('interval','D') == 'D' and raw.get('data') == {'candles':[]}:
                break
            parsed = parse_daily_history(raw,start,end,matches[0]['id'])
        except (ValueError,TypeError,KeyError,AttributeError):
            raise HistorySourceUnavailable('Historical source fields are missing or invalid') from None
        combined = parsed['bars'] + combined
        if len(combined) >= 200:
            break
        end = start-timedelta(days=1)
    return dict(bars=combined,last_observation=datetime.fromisoformat(combined[-1]['time']),
        source_reference=f'kotak-history:{matches[0]["id"]}:D:{start}:{final_end}',
        limitations=['At most three nonoverlapping 180-calendar-day batches under the shared deadline; long lookbacks may remain unavailable. Closed historical bars are not current exchange quotes. Adjustments are not independently verified.'])


def parse_daily_history(raw,start,end,instrument_id):
    if not isinstance(raw,dict) or raw.get('interval','D')!='D':
        raise ValueError('Invalid daily history envelope')
    records = raw.get('data',{}).get('candles')
    if not isinstance(records,list) or not 1<=len(records)<=500:
        raise ValueError('Invalid bounded daily candle batch')
    bars,days = [],set()
    for row in records:
        if not isinstance(row,list) or not 6<=len(row)<=7:
            raise ValueError('Invalid documented positional candle')
        if not isinstance(row[0],str) or any(isinstance(value,bool) for value in row[1:6]):
            raise ValueError('Invalid documented candle types')
        bar = HistoricalBar(time=row[0],open=row[1],high=row[2],low=row[3],close=row[4],volume=row[5])
        day = bar.time.astimezone(ZoneInfo('Asia/Kolkata')).date()
        if not start<=day<=end or day in days or bars and bar.time<=bars[-1].time:
            raise ValueError('Unordered or out-of-range historical observations')
        bars.append(bar)
        days.add(day)
    return dict(bars=[bar.model_dump(mode='json') for bar in bars],last_observation=bars[-1].time,
        source_reference=f'kotak-history:{instrument_id}:D:{start}:{end}',
        limitations=['One bounded 180-calendar-day daily batch; long lookbacks may remain unavailable. Closed historical bars are not current exchange quotes. Adjustments are not independently verified.'])
