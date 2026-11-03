"""Validated option-chain contract shared by MCP and chat."""
import math
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator
from app.brokers.base_broker import BrokerError


class OptionsContext(BaseModel):
    underlying: str = Field(default='NIFTY', min_length=1, max_length=40, pattern=r'^[A-Za-z0-9 &_.-]+$')
    exchange: Literal['nse_fo', 'bse_fo'] = 'nse_fo'
    expiry: str | None = Field(default=None, max_length=40, pattern=r'^[A-Za-z0-9 /:._+-]+$')

    @field_validator('underlying')
    @classmethod
    def normalize_symbol(cls, value):
        value = value.strip().upper()
        if not value:
            raise ValueError('Enter an underlying.')
        return value


class ChatRequest(OptionsContext):
    message: str = Field(min_length=1, max_length=2000)
    conversation_id: UUID | None = None

    @field_validator('message')
    @classmethod
    def nonempty_message(cls, value):
        if not value.strip():
            raise ValueError('Enter a question.')
        return value.strip()


def number(value, *, required=False):
    if isinstance(value, bool):
        raise ValueError('Boolean market value')
    if value is None or value == '':
        if required:
            raise ValueError('Missing price or strike')
        return None
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError('Invalid option value')
    return result


def identity(value):
    return str(value).strip().upper()


def expiry_identity(value):
    value = identity(value)
    for fmt in ('%d%b%Y', '%Y-%m-%d', '%d-%b-%Y', '%d/%m/%Y'):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass
    return value


def normalize_snapshot(raw, context: OptionsContext):
    data = raw.get('data', raw) if isinstance(raw, dict) else None
    if not isinstance(data, dict):
        raise BrokerError('Unexpected option-chain response. No substitute data was used.')
    try:
        common = data['common_data']
        if not isinstance(common, dict):
            raise ValueError('Missing contract metadata')
        verified = {}
        for field, keys, expected, convert in (
            ('underlying', ('underlying', 'underlyingSymbol'), context.underlying, identity),
            ('exchange', ('exchange', 'exchange_segment'), context.exchange, identity),
            ('expiry', ('expiryDt', 'expiry'), context.expiry, expiry_identity),
        ):
            values = [common[key] for key in keys if common.get(key) not in (None, '')]
            if values and any(convert(v) != convert(values[0]) for v in values[1:]):
                raise ValueError('Contradictory provider identity aliases')
            verified[field] = bool(values) and (field != 'expiry' or expected is not None)
            if values and expected is not None and any(convert(v) != convert(expected) for v in values):
                raise ValueError('Contradictory market identity')
        rows = []
        for side, kind in [('call', 'CALL'), ('put', 'PUT')]:
            legs = data[side]
            if not isinstance(legs, list) or len(legs) > 100:
                raise ValueError('Unexpected chain size')
            for leg in legs:
                instrument = leg.get('instrument', leg.get('inst'))
                quote = leg['quote']
                oi = leg.get('openInterest', leg.get('oi')) or {}
                if not all(isinstance(item, dict) for item in (instrument, quote, oi)):
                    raise ValueError('Invalid nested option fields')
                rows.append({
                    'side': kind,
                    'symbol': str(instrument['symbol'])[:100],
                    'strike': number(instrument.get('strikePrice', instrument.get('strkPrc')), required=True),
                    'ltp': number(quote.get('ltp'), required=True),
                    'volume': number(quote.get('volume', quote.get('vol'))),
                    'open_interest': number(oi.get('current', oi.get('cur'))),
                })
        if not rows:
            raise ValueError('Empty option chain')
        call_oi = [r['open_interest'] for r in rows if r['side'] == 'CALL']
        put_oi = [r['open_interest'] for r in rows if r['side'] == 'PUT']
        complete_oi = bool(call_oi and put_oi) and all(x is not None for x in call_oi + put_oi)
        calls = sum(call_oi) if complete_oi else None
        puts = sum(put_oi) if complete_oi else None
        ratio = puts / calls if complete_oi and calls else None
        for value in (calls, puts, ratio):
            if value is not None:
                number(value)
        highest = {}
        for side in ('CALL', 'PUT'):
            eligible = [r for r in rows if r['side'] == side and r['open_interest'] is not None]
            highest[side] = max(eligible, key=lambda r: r['open_interest']) if eligible else None
        return {
            'snapshot_id': str(uuid4()), 'source': 'kotak',
            'retrieved_at': datetime.now(UTC).isoformat(),
            'exchange_timestamp': None,
            'identity_verification': verified,
            'underlying': context.underlying, 'exchange': context.exchange,
            'expiry': str(common.get('expiryDt') or common.get('expiry') or context.expiry or 'Provider-selected expiry')[:80],
            'lot_size': number(common.get('mktLot')),
            'rows': sorted(rows, key=lambda r: (r['strike'], r['side'])),
            'summary': {'call_open_interest': calls, 'put_open_interest': puts,
                        'put_call_ratio': ratio,
                        'highest_open_interest': highest},
            'limitations': [
                'Market identity is verified only for metadata supplied by the provider; see identity_verification.',
                'REST snapshot; retrieval time is not an exchange quote timestamp. Freshness is unverified.',
                'Open-interest totals and put/call ratio cover returned strikes only, not the whole market.',
                'IV, Greeks, bid/ask spreads and exchange timestamps are unavailable in this tool.',
                'Monitoring refreshes only while this page is open; no background alerts are active.',
            ],
        }
    except (KeyError, AttributeError, TypeError, ValueError, OverflowError):
        raise BrokerError('Option-chain fields are missing or invalid. No substitute data was used.') from None


class SnapshotService:
    def __init__(self, market):
        self.market = market

    def fetch(self, user_id, context):
        raw = self.market.call('option_chain', user_id=user_id, exchange=context.exchange,
                               underlying=context.underlying, expiry=context.expiry,
                               instrument_type='option', count=20)
        return normalize_snapshot(raw, context)

