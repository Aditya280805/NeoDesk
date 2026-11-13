"""Broker data boundary; catalogue downloads are restricted to Kotak hosts."""
from contextlib import contextmanager
import csv
import hashlib
import io
import json
import logging
import math
import os
import time
from datetime import UTC, datetime, timedelta
from threading import RLock
from uuid import uuid4
from urllib.parse import urlparse

import httpx
from pydantic import SecretStr

from app.brokers.base_broker import BrokerError
from app.brokers.kotak_neo.kotak_broker import KotakNeoBroker
from app.core.config import Instrument
from app.terminal.catalogue import normalise, quote_token

SEGMENTS = ('nse_cm', 'bse_cm', 'nse_fo', 'bse_fo')


class MarketDeadlineError(TimeoutError):
    """Internal safe request-budget expiry; SDK timeout messages stay private."""

class MarketQuotaError(BrokerError):
    """Typed quota signal; retry delay is metadata, never error-text parsing."""
    def __init__(self,retry_after=60):
        super().__init__('Kotak rate limit reached. Wait before refreshing; no substitute data was used.')
        self.retry_after=retry_after



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
                     'source_metadata': {'source': 'kotak-scrip-master',
                                         'lLotSize': row.get('lLotSize', ''),
                                         'pInstType': row.get('pInstType', '')},
                     'identity_source_fields': {key:row.get(key,'') for key in ('pSymbol','pSymbolName','pExchSeg','pTrdSymbol','pOptionType','lExpiryDate','pExpiryDate','dStrikePrice','pGroup','pISIN')},
                     'strike': number('dStrikePrice', 0) / 100, 'isin': row.get('pISIN', '')})
    if not rows:
        raise BrokerError(f'Kotak returned no valid instruments for {segment}.')
    return [normalise(i) for i in rows]


class UserMarketSession:
    def __init__(self, config):
        self.config = config.model_copy(deep=True)
        self.broker = KotakNeoBroker(self.config)
        self.source = 'kotak' if self.config.market_data_source == 'kotak' and self.config.kotak_consumer_key else 'demo'
        self.last_error = None
        self.last_request = 0.0
        self.portfolio_cache = None
        self.generation = str(uuid4())
        self.portfolio_lock = RLock()


class Market:
    """
    Interface to the broker's market data APIs.
    
    Handles downloading the instrument master catalogue, fetching real-time quotes, 
    and retrieving historical candlestick data. Implements thread-safe caching and 
    rate limiting to protect the broker connection. Supports per-user broker sessions.
    """
    def __init__(self, config, store):
        os.environ['NEO_LOG_FILE_ENABLED'] = 'false'
        os.environ['NEO_LOG_LEVEL'] = 'NOLOG'
        self.config, self.store = config.model_copy(deep=True), store
        self.lock = RLock()
        self.call_lock = RLock()
        self.user_sessions = {}
        u1_sess = UserMarketSession(self.config)
        self.user_sessions[1] = u1_sess
        self.broker = u1_sess.broker
        self.cache = {}
        self.history_cache = {}
        self.history_lock = RLock()
        self.last_request = 0.0
        self.source = u1_sess.source
        self.last_error = None
        self.seed()
        # Kotak's cash master omits some index references that have F&O contracts.
        index=normalise({'id':'nse_cm|Nifty Next 50','token':'Nifty Next 50','exchange':'nse_cm','symbol':'NIFTYNXT50','name':'Nifty Next 50','underlying':'NIFTYNXT50','kind':'INDEX','lot_size':1,'tick_size':.05,'expiry':'','option_type':'','strike':0,'isin':''})
        with self.store.connect() as db:
            db.execute('INSERT OR IGNORE INTO instruments VALUES (?,?,?,?,?,?,?)',(index['id'],index['symbol'],index['name'],index['exchange'],index['kind'],index['underlying'],json.dumps(index)))

    def get_session(self, user_id: int = 1) -> UserMarketSession:
        with self.lock:
            if user_id not in self.user_sessions:
                cfg = self.config.model_copy(deep=True)
                cfg.kotak_consumer_key = None
                cfg.kotak_ucc = None
                cfg.kotak_mobile_number = None
                cfg.market_data_source = 'sample'
                self.user_sessions[user_id] = UserMarketSession(cfg)
            return self.user_sessions[user_id]

    def session_generation(self, user_id: int) -> str:
        with self.lock:
            return self.get_session(user_id).generation

    def sign_in(self, key: str, ucc: str, mobile: str, totp: str, mpin: str):
        """Authenticate a fresh broker session before assigning any website identity."""
        cfg = self.config.model_copy(deep=True)
        cfg.kotak_consumer_key = SecretStr(key)
        cfg.kotak_ucc, cfg.kotak_mobile_number = ucc, mobile
        cfg.kotak_mpin = None
        cfg.market_data_source = 'kotak'
        candidate = UserMarketSession(cfg)
        try:
            candidate.broker.login(totp, mpin)
            identity = hashlib.sha256(f'kotak:{ucc.upper()}'.encode()).hexdigest()
            user = self.store.broker_user(identity, f'Kotak • {ucc[-4:]}', self.config.paper_starting_balance)
            with self.lock:
                old = self.user_sessions.get(user['id'])
                self.user_sessions[user['id']] = candidate
                if old:
                    old.broker.close()
            return user
        except Exception:
            candidate.broker.close()
            raise

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
            self.store.watch(1, 'nse_cm|' + token)
        with self.store.connect() as db:
            db.execute("DELETE FROM metadata WHERE key='catalogue_updated_at'")

    def connect(self, key, user_id: int = 1):
        if not key.strip() or len(key) > 2048:
            raise BrokerError('Enter a valid Kotak consumer key.')
        with self.lock:
            sess = self.get_session(user_id)
            sess.broker.close()
            sess.config.kotak_consumer_key = SecretStr(key.strip())
            sess.broker = KotakNeoBroker(sess.config)
            sess.source = 'kotak'
            sess.last_error = None
            sess.portfolio_cache = None
            sess.generation = str(uuid4())
            if user_id == 1:
                self.config.kotak_consumer_key = sess.config.kotak_consumer_key
                self.broker = sess.broker
                self.source = 'kotak'
            self.cache.clear()
            self.history_cache.clear()
            try:
                if not self.quotes(['nse_cm|1333'], user_id=user_id):
                    raise BrokerError('Kotak returned no usable quote to verify this connection.')
            except Exception:
                sess.source = 'demo'
                sess.config.kotak_consumer_key = None
                sess.broker.close()
                if user_id == 1:
                    self.source = 'demo'
                    self.config.kotak_consumer_key = None
                raise
        self.store.audit(user_id, 'broker_connected', 'Kotak quote access verified; token kept in server memory only.')

    def disconnect(self, user_id: int = 1):
        with self.lock:
            sess = self.get_session(user_id)
            sess.broker.close()
            sess.config.kotak_consumer_key = None
            sess.source = 'demo'
            sess.last_error = None
            sess.portfolio_cache = None
            sess.generation = str(uuid4())
            if user_id == 1:
                self.broker.close()
                self.config.kotak_consumer_key = None
                self.source = 'demo'
            self.cache.clear()
            self.history_cache.clear()

    def broker_login(self, ucc: str, mobile: str, totp: str, mpin: str, user_id: int = 1) -> bool:
        with self.lock:
            sess = self.get_session(user_id)
            if sess.source != 'kotak':
                raise ValueError('Connect the consumer key first.')
            sess.config.kotak_ucc = ucc
            sess.config.kotak_mobile_number = mobile
            sess.generation = str(uuid4())
            sess.portfolio_cache = None
            sess.broker.login(totp, mpin)
            if user_id == 1:
                self.config.kotak_ucc = ucc
                self.config.kotak_mobile_number = mobile
            return sess.broker.is_authenticated

    @staticmethod
    @contextmanager
    def _request_lock(lock, deadline_monotonic):
        """Bound the actual acquisition, including nested lifecycle boundaries."""
        if deadline_monotonic is None:
            lock.acquire()
        else:
            remaining = deadline_monotonic - time.monotonic()
            if remaining <= 0 or not lock.acquire(timeout=remaining):
                raise MarketDeadlineError('Portfolio request deadline expired.')
        try:
            if deadline_monotonic is not None and time.monotonic() >= deadline_monotonic:
                raise MarketDeadlineError('Portfolio request deadline expired.')
            yield
        finally:
            lock.release()

    def call(self, method, user_id: int = 1, *, deadline_monotonic=None, **kwargs):
        with self._request_lock(self.call_lock, deadline_monotonic):
            with self._request_lock(self.lock, deadline_monotonic):
                # get_session's nested RLock acquisition is immediate while owned.
                sess = self.get_session(user_id)
                broker_to_call = sess.broker if sess.source == 'kotak' else None
                generation = sess.generation
            if not broker_to_call:
                raise BrokerError('Connect Kotak in Connections to request broker data.')
            
            is_running = False
            try:
                import asyncio
                asyncio.get_running_loop()
                is_running = True
            except RuntimeError:
                pass

            if is_running:
                raise RuntimeError('Market.call() blocked the event loop. Use run_in_threadpool.')

            delay = (2.0 if method == 'historical_data' else .25) - (time.monotonic() - self.last_request)
            if deadline_monotonic is not None and time.monotonic()+max(0,delay) >= deadline_monotonic:
                raise MarketDeadlineError('Portfolio request deadline expired.')
            if delay > 0:
                time.sleep(delay)
            if deadline_monotonic is not None and time.monotonic() >= deadline_monotonic:
                raise MarketDeadlineError('Portfolio request deadline expired.')
            try:
                result = getattr(broker_to_call._sdk(), method)(**kwargs)
                if method in ('holdings','positions','order_report','limits'):
                    from .portfolio_source_diagnostics import source_shape
                    logging.getLogger(__name__).info('portfolio_source_shape method=%s shape=%s',method,source_shape(result))
                if isinstance(result, dict) and ('rate limit' in str(result.get('error', '')).lower() or str(result.get('stCode',result.get('status_code','')))=='429'):
                    headers=result.get('headers') if isinstance(result.get('headers'),dict) else {}
                    raise MarketQuotaError(headers.get('Retry-After',headers.get('retry-after',60)))
                if isinstance(result, dict) and result.get('error') == 'Service temporarily unavailable':
                    raise BrokerError('Kotak market-data service is temporarily unavailable. Please try later.')
                if isinstance(result, dict) and (any(result.get(k) for k in ('error', 'Error', 'Error Message', 'fault')) or str(result.get('stat', result.get('status', ''))).lower() in ('error','failed','not_ok') or str(result.get('stCode', '200')) in ('401','403')):
                    if str(result.get('stCode', '')) in ('401','403') or result.get('Error Message'):
                        with self._request_lock(self.lock, deadline_monotonic):
                            current = self.user_sessions.get(user_id)
                            if current is sess and current.broker is broker_to_call and current.generation == generation:
                                current.generation = str(uuid4())
                                current.portfolio_cache = None
                                broker_to_call.close()
                    raise ValueError('Broker rejected request')
                return result
            except (BrokerError, MarketDeadlineError):
                raise
            except Exception:
                raise BrokerError(f'Kotak {method} request failed. Check connection, API permissions and rate limits.') from None
            finally:
                self.last_request = time.monotonic()

    def sync(self, user_id: int = 1):
        all_rows = []
        for segment in SEGMENTS:
            url = self.call('scrip_master', user_id=user_id, exchange_segment=segment)
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
        self.store.audit(user_id, 'catalogue_sync', f'Imported {len(all_rows)} instruments across NSE/BSE cash and derivatives.')
        return self.store.metadata()

    def quotes(self, identifiers, user_id: int = 1):
        if len(identifiers) > 50:
            raise ValueError('Request at most 50 quotes at once.')
        instruments = [self.store.instrument(i) for i in dict.fromkeys(identifiers)]
        if not instruments:
            return []
        with self.lock:
            sess = self.get_session(user_id)
            broker_to_use = sess.broker if sess.source == 'kotak' else None
            if broker_to_use is None or (sess.source == 'demo' and self.source == 'demo'):
                return [{'id': i['id'], 'symbol': i['symbol'], 'ltp': self.demo_price(i['id']),
                         'change_pct': 0, 'source': 'demo', 'received_at': datetime.now(UTC).isoformat(),
                         'last_trade_time': None} for i in instruments]
            key = (user_id, tuple(i['id'] for i in instruments))
            cached = self.cache.get(key)
            if cached and time.monotonic() - cached[0] < 3:
                return cached[1]
            ids_by_token={(i['exchange'],quote_token(i)):i['id'] for i in instruments}
            broker_to_use.config.kotak_instruments = [Instrument(exchange_segment=i['exchange'], instrument_token=quote_token(i)) for i in instruments]
            broker_to_use._cache = None
            is_running = False
            try:
                import asyncio
                asyncio.get_running_loop()
                is_running = True
            except RuntimeError:
                pass

            if is_running:
                raise RuntimeError('Market.quotes() blocked the event loop. Use run_in_threadpool.')

            try:
                delay=.25-(time.monotonic()-self.last_request)
                if delay>0:
                    time.sleep(delay)
                rows = broker_to_use.get_quotes(strict=False)
                rows = [{**q, 'id': ids_by_token[(q['exchange_segment'],q['instrument_token'])]} for q in rows]
            except BrokerError as exc:
                sess.last_error = str(exc)
                self.last_error = str(exc)
                raise
            finally:
                self.last_request=time.monotonic()
            self.cache[key] = (time.monotonic(), rows)
            if len(self.cache) > 100:
                self.cache = {key: self.cache[key]}
            sess.last_error = None
            self.last_error = None
            return rows


    @staticmethod
    def demo_price(identifier):
        return round(100 + int(hashlib.sha256(identifier.encode()).hexdigest()[:6], 16) % 200000 / 100, 2)

    def history(self, identifier, interval='D', days=365, user_id: int = 1):
        with self.history_lock:
            return self._history(identifier,interval,days,user_id)

    def _history(self, identifier, interval='D', days=365, user_id: int = 1):
        instrument=self.store.instrument(identifier)
        maximum = {'1min':30,'5min':30,'15min':60,'60min':90,'D':180}[interval]
        if days < 1 or days > (540 if interval == 'D' else maximum):
            raise ValueError(f'{interval} supports 1–{540 if interval == "D" else maximum} days in this terminal.')
        end = (datetime.now(UTC) + timedelta(hours=5, minutes=30)).date()
        if (self.source if user_id==1 else self.get_session(user_id).source) == 'demo':
            candles = []
            base = self.demo_price(identifier)
            for n in range(260):
                day = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=260-n)
                close = base * (1 + .06 * math.sin(n / 13) + .0005*n)
                opening = close * (1 + .005*math.sin(n))
                candles.append({'time': int(day.timestamp()), 'open':round(opening,2), 'high':round(max(opening,close)*1.01,2),
                                'low':round(min(opening,close)*.99,2), 'close':round(close,2), 'volume':10000+n*200})
            return {'source':'demo','interval':'D','candles':candles, 'note':'Synthetic daily candles for interface testing.'}
        key = (user_id, identifier, interval, days, end.isoformat())
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
                raw = self.call('historical_data', user_id=user_id, neosymbol=instrument['exchange']+'|'+quote_token(instrument), interval=interval,
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
                if len(values) != 5 or not all(math.isfinite(v) for v in values):
                    raise ValueError()
                o,h,l,c,v = values
                # Kotak API sometimes returns malformed candles where open/close is outside high/low bounds, or negative volume.
                v = max(0, v)
                h = max(h, o, c)
                l = min(l, o, c)
                if c <= 0 or min(o,h,l,c) < 0:
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
