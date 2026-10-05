"""Broker data boundary; catalogue downloads are restricted to Kotak hosts."""
import csv
import hashlib
import io
import math
import os
import time
from datetime import UTC, datetime, timedelta
from threading import RLock
from urllib.parse import urlparse

import httpx
from pydantic import SecretStr

from app.brokers.base_broker import BrokerError
from app.brokers.kotak_neo.kotak_broker import KotakNeoBroker
from app.core.config import Instrument
from app.terminal.catalogue import normalise

SEGMENTS = ('nse_cm', 'bse_cm', 'nse_fo', 'bse_fo')


def parse_master(text, segment):
    reader = csv.DictReader(io.StringIO(text.lstrip('\ufeff')))
    rows = []
    for raw in reader:
        row = {k.strip().rstrip(';'): (v or '').strip() for k, v in raw.items() if k}
        token, symbol = row.get('pSymbol'), row.get('pTrdSymbol')
        if not token or not symbol:
            continue
        inst = row.get('pInstType', '').upper()
        kind = 'OPTION' if inst.startswith('OPT') or inst in ('IO', 'SO') else 'FUTURE' if inst.startswith('FUT') or inst in ('IF', 'SF') else 'OTHER'
        if segment.endswith('_cm'):
            if not row.get('pISIN') and not row.get('pGroup'):
                kind = 'INDEX'
            elif 'ETF' in row.get('pDesc', '').upper() or 'ETF' in inst or (segment == 'bse_cm' and row.get('pGroup') == 'E'):
                kind = 'ETF'
            elif row.get('pGroup') in ('EQ', 'BE', 'BZ', 'SM', 'ST', 'A', 'B', 'T', 'X', 'XT', 'Z', 'M', 'MT', 'MS', 'TS', 'P', 'ZP') or inst in ('ES', 'EQUITY'):
                kind = 'EQUITY'
        def number(key, default):
            try:
                value = float(row.get(key, ''))
                return value if math.isfinite(value) and value > 0 else default
            except (ValueError, TypeError):
                return default
        # Kotak master represents strike/tick values in paise for these segments.
        tick = number('dTickSize', 5) / 100
        rows.append({'id': f'{segment}|{token}', 'token': token, 'exchange': segment,
                     'symbol': symbol, 'name': row.get('pDesc') or row.get('pSymbolName') or symbol,
                     'underlying': row.get('pSymbolName', ''), 'kind': kind,
                     'lot_size': int(number('lLotSize', 1)), 'tick_size': tick,
                     'expiry': row.get('lExpiryDate') or row.get('pExpiryDate', ''), 'option_type': row.get('pOptionType', ''),
                     'instrument_type': inst,
                     'strike': number('dStrikePrice', 0) / 100, 'isin': row.get('pISIN', '')})
    if not rows:
        raise BrokerError(f'Kotak returned no valid instruments for {segment}.')
    return [normalise(i) for i in rows]


class Market:
    def __init__(self, config, store):
        os.environ['NEO_LOG_FILE_ENABLED'] = 'false'
        os.environ['NEO_LOG_LEVEL'] = 'NOLOG'
        self.config, self.store = config.model_copy(deep=True), store
        self.broker = KotakNeoBroker(self.config)
        self.lock = RLock()
        self.cache = {}
        self.history_cache = {}
        self.last_request = 0.0
        self.source = 'kotak' if config.market_data_source == 'kotak' and config.kotak_consumer_key else 'demo'
        self.last_error = None
        self.seed()

    def seed(self):
        if self.store.metadata()['total']:
            return
        seeds = [('26000', 'NIFTY', 'INDEX'), ('26009', 'BANKNIFTY', 'INDEX'),
                 ('1333', 'HDFCBANK-EQ', 'EQUITY'), ('2885', 'RELIANCE-EQ', 'EQUITY'),
                 ('1594', 'INFY-EQ', 'EQUITY'), ('11536', 'TCS-EQ', 'EQUITY'), ('3045', 'SBIN-EQ', 'EQUITY')]
        self.store.save_catalogue([{'id': 'nse_cm|' + t, 'token': t, 'symbol': s, 'name': s,
            'exchange': 'nse_cm', 'underlying': s.split('-')[0], 'kind': k, 'lot_size': 1,
            'tick_size': .05, 'expiry': '', 'option_type': '', 'strike': 0, 'isin': ''} for t,s,k in seeds], ['nse_cm'])
        for token, _, _ in seeds[:4]:
            self.store.watch('nse_cm|' + token)
        with self.store.connect() as db:
            db.execute("DELETE FROM metadata WHERE key='catalogue_updated_at'")

    def connect(self, key):
        if not key.strip() or len(key) > 2048:
            raise BrokerError('Enter a valid Kotak consumer key.')
        with self.lock:
            self.broker.close()
            self.config.kotak_consumer_key = SecretStr(key.strip())
            self.broker = KotakNeoBroker(self.config)
            self.source = 'kotak'
            self.cache.clear()
            self.history_cache.clear()
            try:
                if not self.quotes(['nse_cm|1333']):
                    raise BrokerError('Kotak returned no usable quote to verify this connection.')
            except Exception:
                self.source = 'demo'
                self.config.kotak_consumer_key = None
                self.broker.close()
                raise
        self.store.audit('broker_connected', 'Kotak quote access verified; token kept in server memory only.')

    def disconnect(self):
        with self.lock:
            self.broker.close()
            self.config.kotak_consumer_key = None
            self.cache.clear()
            self.history_cache.clear()
            self.source = 'demo'

    def call(self, method, **kwargs):
        with self.lock:
            if self.source != 'kotak':
                raise BrokerError('Connect Kotak in Connections to request broker data.')
            delay = (2.0 if method == 'historical_data' else .25) - (time.monotonic() - self.last_request)
            if delay > 0:
                time.sleep(delay)
            try:
                result = getattr(self.broker._sdk(), method)(**kwargs)
                if isinstance(result, dict) and 'rate limit' in str(result.get('error', '')).lower():
                    raise BrokerError('Kotak rate limit reached. Wait before refreshing; no substitute data was used.')
                if isinstance(result, dict) and result.get('error') == 'Service temporarily unavailable':
                    raise BrokerError('Kotak market-data service is temporarily unavailable. Please try later.')
                if isinstance(result, dict) and (any(result.get(k) for k in ('error', 'Error', 'fault')) or str(result.get('status', '')).lower() in ('error','failed')):
                    raise ValueError('Broker rejected request')
                return result
            except BrokerError:
                raise
            except Exception:
                raise BrokerError(f'Kotak {method} request failed. Check connection, API permissions and rate limits.') from None
            finally:
                self.last_request = time.monotonic()

    def sync(self):
        all_rows = []
        for segment in SEGMENTS:
            url = self.call('scrip_master', exchange_segment=segment)
            if not isinstance(url, str):
                raise BrokerError('Unexpected instrument-master response.')
            parsed = urlparse(url)
            if parsed.scheme != 'https' or parsed.hostname != 'lapi.kotaksecurities.com' or parsed.port not in (None,443):
                raise BrokerError('Unexpected instrument-master host.')
            try:
                # No credentials are forwarded to CSV download URLs. No redirects.
                with httpx.stream('GET', url, timeout=45, follow_redirects=False) as response:
                    response.raise_for_status()
                    content = bytearray()
                    for chunk in response.iter_bytes():
                        content.extend(chunk)
                        if len(content) > 100_000_000:
                            raise ValueError('Master too large')
                all_rows.extend(parse_master(content.decode('utf-8-sig'), segment))
            except Exception:
                raise BrokerError(f'Could not import {segment}; the previous catalogue is unchanged.') from None
        self.store.save_catalogue(all_rows, SEGMENTS)
        self.store.audit('catalogue_sync', f'Imported {len(all_rows)} instruments across NSE/BSE cash and derivatives.')
        return self.store.metadata()

    def quotes(self, identifiers):
        if len(identifiers) > 50:
            raise ValueError('Request at most 50 quotes at once.')
        instruments = [self.store.instrument(i) for i in dict.fromkeys(identifiers)]
        if not instruments:
            return []
        with self.lock:
            if self.source == 'demo':
                return [{'id': i['id'], 'symbol': i['symbol'], 'ltp': self.demo_price(i['id']),
                         'change_pct': 0, 'source': 'demo', 'received_at': datetime.now(UTC).isoformat(),
                         'last_trade_time': None} for i in instruments]
            key = tuple(i['id'] for i in instruments)
            cached = self.cache.get(key)
            if cached and time.monotonic() - cached[0] < 3:
                return cached[1]
            self.broker.config.kotak_instruments = [Instrument(exchange_segment=i['exchange'], instrument_token=i['token']) for i in instruments]
            self.broker._cache = None
            try:
                delay=.25-(time.monotonic()-self.last_request)
                if delay>0:
                    time.sleep(delay)
                rows = self.broker.get_quotes(strict=False)
                rows = [{**q, 'id': f"{q['exchange_segment']}|{q['instrument_token']}"} for q in rows]
            except Exception:
                self.last_error = 'Kotak quotes unavailable'
                raise BrokerError('Kotak quotes unavailable; no substitute prices were used.') from None
            finally:
                self.last_request=time.monotonic()
            self.cache[key] = (time.monotonic(), rows)
            if len(self.cache) > 100:
                self.cache = {key: self.cache[key]}
            self.last_error = None
            return rows

    @staticmethod
    def demo_price(identifier):
        return round(100 + int(hashlib.sha256(identifier.encode()).hexdigest()[:6], 16) % 200000 / 100, 2)

    def history(self, identifier, interval='D', days=365):
        self.store.instrument(identifier)
        maximum = {'1min':30,'5min':30,'15min':60,'60min':90,'D':180}[interval]
        if days < 1 or days > (540 if interval == 'D' else maximum):
            raise ValueError(f'{interval} supports 1–{540 if interval == "D" else maximum} days in this terminal.')
        end = (datetime.now(UTC) + timedelta(hours=5, minutes=30)).date()
        if self.source == 'demo':
            candles = []
            base = self.demo_price(identifier)
            for n in range(260):
                day = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=260-n)
                close = base * (1 + .06 * math.sin(n / 13) + .0005*n)
                opening = close * (1 + .005*math.sin(n))
                candles.append({'time': int(day.timestamp()), 'open':round(opening,2), 'high':round(max(opening,close)*1.01,2),
                                'low':round(min(opening,close)*.99,2), 'close':round(close,2), 'volume':10000+n*200})
            return {'source':'demo','interval':'D','candles':candles, 'note':'Synthetic daily candles for interface testing.'}
        key = (identifier, interval, days, end.isoformat())
        cached = self.history_cache.get(key)
        if cached and time.monotonic() - cached[0] < 60:
            return cached[1]
        # The broker counts BOTH endpoints. Split daily history to warm up SMA 200.
        start = end - timedelta(days=days-1)
        rows = []
        warnings = []
        while start <= end:
            batch_end = min(end, start + timedelta(days=maximum-1))
            try:
                raw = self.call('historical_data', neosymbol=identifier, interval=interval,
                                from_date=start.isoformat(), to_date=batch_end.isoformat())
                rows.extend(raw['data']['candles'])
                if 'partial' in str(raw.get('message','')).lower():
                    warnings.append(f'{start} to {batch_end}: broker reported a partial response.')
            except BrokerError as exc:
                warnings.append(f'{start} to {batch_end}: {exc}')
                if 'rate limit' in str(exc).lower():
                    break
            except (KeyError, TypeError):
                raise BrokerError('Unexpected historical candle response.') from None
            start = batch_end + timedelta(days=1)
        if not rows and warnings:
            raise BrokerError('History unavailable. ' + warnings[0])
        try:
            candles = []
            for row in rows:
                values = [float(v) for v in row[1:6]]
                if len(values) != 5 or not all(math.isfinite(v) and v >= 0 for v in values):
                    raise ValueError()
                o,h,l,c,v = values
                if min(o,c) < l or max(o,c) > h or c <= 0:
                    raise ValueError()
                stamp = datetime.fromisoformat(row[0])
                if interval == 'D':
                    stamp = datetime.combine(stamp.date(), datetime.min.time(), tzinfo=UTC)
                candles.append({'time':int(stamp.timestamp()), 'open':o,'high':h,'low':l,'close':c,'volume':v})
            candles = sorted({c['time']:c for c in candles}.values(),key=lambda x:x['time'])
        except Exception:
            raise BrokerError('Unexpected historical candle response.') from None
        note = 'History as supplied by Kotak; corporate action adjustment is not verified. The latest candle may still be forming.'
        if warnings:
            note = 'INCOMPLETE HISTORY: ' + ' '.join(warnings) + ' ' + note
        result = {'source':'kotak','interval':interval,'candles':candles,'partial':bool(warnings),'note':note}
        self.history_cache[key] = (time.monotonic(), result)
        if len(self.history_cache) > 30:
            self.history_cache = {key:self.history_cache[key]}
        return result
