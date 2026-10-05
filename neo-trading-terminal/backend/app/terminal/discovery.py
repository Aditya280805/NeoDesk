import json
import time
from datetime import datetime
from app.terminal.catalogue import INDEX_NAMES, IST, contract_open

FEATURED_STOCKS=('RELIANCE','HDFCBANK','ICICIBANK','INFY','TCS','SBIN','BHARTIARTL','ITC',
                 'LT','AXISBANK','KOTAKBANK','BAJFINANCE','MARUTI','M&M','TATASTEEL','SUNPHARMA',
                 'NTPC','POWERGRID','TITAN','HINDUNILVR')


class Discovery:
    def __init__(self, store, market):
        self.store,self.market=store,market
        self.activity_cache={}

    def indices(self, query=''):
        with self.store.connect() as db:
            spots=[json.loads(r[0]) for r in db.execute("SELECT payload FROM instruments WHERE kind='INDEX'")]
            derivatives=[json.loads(r[0]) for r in db.execute("SELECT payload FROM instruments WHERE kind IN ('OPTION','FUTURE') AND exchange IN ('nse_fo','bse_fo')")]
        known={(s['exchange'].replace('_cm','_fo'),s['underlying'] or s['symbol']) for s in spots}
        known.update((i['exchange'],i['underlying']) for i in derivatives if i.get('instrument_type') in ('OPTIDX','FUTIDX','IO','IF') or i['underlying'] in INDEX_NAMES)
        result=[]
        term=''.join(query.upper().split())
        for exchange,symbol in sorted(known):
            name=INDEX_NAMES.get(symbol,symbol)
            if term and term not in ''.join((name+symbol).upper().split()):
                continue
            contracts=[i for i in derivatives if i['exchange']==exchange and i['underlying']==symbol and contract_open(i)]
            spot=next((s for s in spots if s['exchange']==exchange.replace('_fo','_cm') and (s['underlying'] or s['symbol'])==symbol),None)
            result.append({'id':exchange+'|'+symbol,'symbol':symbol,'name':name,'exchange':exchange,
                           'spot':spot,'options_count':sum(i['kind']=='OPTION' for i in contracts),
                           'futures_count':sum(i['kind']=='FUTURE' for i in contracts)})
        return result

    def contracts(self, underlying, exchange, kind, expiry='', option_type='', offset=0, limit=30, strike=None):
        with self.store.connect() as db:
            rows=[json.loads(r[0]) for r in db.execute('SELECT payload FROM instruments WHERE underlying=? AND exchange=? AND kind=?', (underlying,exchange,kind))]
        active=[i for i in rows if contract_open(i)]
        expiries=sorted({i['expiry'] for i in active})
        selected=expiry or (expiries[0] if expiries else '')
        filtered=[i for i in active if (kind=='FUTURE' and not expiry or i['expiry']==selected) and (not option_type or i.get('option_type')==option_type) and (strike is None or i.get('strike')==strike)]
        filtered.sort(key=lambda i:(i['expiry'],i.get('strike',0),i.get('option_type','')))
        return {'items':filtered[offset:offset+limit],'total':len(filtered),'expiries':expiries,'expiry':selected}

    def activity(self, scope, metric):
        stamp=self.store.metadata()['updated_at']
        key=(scope,metric,self.market.source,stamp)
        cached=self.activity_cache.get(key)
        if cached and time.monotonic()-cached[0]<60:
            return cached[1]
        if scope=='stocks':
            with self.store.connect() as db:
                rows=[json.loads(r[0]) for r in db.execute("SELECT payload FROM instruments WHERE exchange='nse_cm' AND kind='EQUITY' AND underlying IN ("+','.join('?' for _ in FEATURED_STOCKS)+")",FEATURED_STOCKS)]
            rows=[i for i in rows if i['symbol'].endswith('-EQ')][:50]
            universe='Selected NSE shares'
        else:
            rows=[]
            for index in self.indices():
                contracts=self.contracts(index['symbol'],index['exchange'],'FUTURE')['items']
                if contracts:
                    rows.append({**contracts[0],'index_name':index['name']})
            rows=rows[:50]
            universe='Nearest-expiry futures for available indices'
        quotes={}
        error=None
        if self.market.source=='kotak' and rows:
            try:
                quotes={q['id']:q for q in self.market.quotes([i['id'] for i in rows])}
            except Exception:
                error='Activity data is temporarily unavailable.'
        field='volume' if metric=='volume' else 'turnover_estimate'
        ranked=[{**i,'quote':quotes[i['id']]} for i in rows if quotes.get(i['id'],{}).get(field) is not None]
        ranked.sort(key=lambda i:i['quote'][field],reverse=True)
        result={'items':ranked[:8],'featured':rows[:8], 'universe':universe,'tracked':len(rows),
                'quoted':len(quotes),'metric':metric,'source':self.market.source,
                'updated_at':datetime.now(IST).isoformat(),'error':error,
                'note':'Ranks only this tracked universe. Traded value is estimated from broker volume × VWAP.'}
        self.activity_cache={key:(time.monotonic(),result),**{k:v for k,v in self.activity_cache.items() if time.monotonic()-v[0]<60 and k!=key}}
        return result
