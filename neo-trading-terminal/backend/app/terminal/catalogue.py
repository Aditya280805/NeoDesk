"""Normalised catalogue fields shared by discovery and paper execution."""
from datetime import UTC, datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
INDEX_NAMES = {'NIFTY':'Nifty 50', 'BANKNIFTY':'Nifty Bank', 'FINNIFTY':'Nifty Financial Services',
               'MIDCPNIFTY':'Nifty Midcap Select', 'NIFTYNXT50':'Nifty Next 50',
               'SENSEX':'Sensex', 'BANKEX':'BSE Bankex', 'SENSEX50':'Sensex 50'}


def expiry_date(value, exchange):
    value = str(value or '').strip()
    if not value or value == '-1':
        return ''
    try:
        stamp = float(value)
        if exchange == 'nse_fo':
            stamp += 315511200  # Kotak instrument-master convention, documented by broker.
        return datetime.fromtimestamp(stamp, IST).date().isoformat()
    except (ValueError, OverflowError, OSError):
        for pattern in ('%Y-%m-%d', '%d%b%Y', '%d-%b-%Y'):
            try:
                return datetime.strptime(value, pattern).date().isoformat()
            except ValueError:
                pass
    return ''


def normalise(item):
    item = dict(item)
    if item['exchange'].endswith('_fo'):
        item['expiry'] = expiry_date(item.get('expiry'), item['exchange'])
        # Repair earlier imports where BSE's IO/SO/IF/SF types were classified OTHER.
        if item['kind'] == 'OTHER':
            if item.get('option_type') in ('CE', 'PE'):
                item['kind'] = 'OPTION'
            elif item['symbol'].endswith('FUT'):
                item['kind'] = 'FUTURE'
    elif 'MUTUAL FUND' in item.get('name', '').upper() and item['kind'] == 'EQUITY':
        item['kind'] = 'OTHER'
    item['display_name'] = INDEX_NAMES.get(item['symbol'], item['name']) if item['kind'] == 'INDEX' else item['name']
    return item


def contract_open(item):
    if item['kind'] not in ('OPTION', 'FUTURE'):
        return True
    expiry = expiry_date(item.get('expiry'), item['exchange'])
    if not expiry:
        return False
    # Stop new simulator trades at the expiry session close; no invented settlement price.
    return datetime.now(IST) < datetime.fromisoformat(expiry + 'T15:30:00').replace(tzinfo=IST)
INDEX_QUOTE_TOKENS = {
    'NIFTY':'Nifty 50', 'BANKNIFTY':'Nifty Bank', 'FINNIFTY':'Nifty Fin Service',
    'MIDCPNIFTY':'NIFTY MID SELECT', 'NIFTYNXT50':'Nifty Next 50',
    'SENSEX':'SENSEX', 'BANKEX':'BANKEX', 'SENSEX50':'SENSEX50',
}

def quote_token(item):
    return INDEX_QUOTE_TOKENS.get(item['symbol'], item['token']) if item['kind']=='INDEX' else item['token']

