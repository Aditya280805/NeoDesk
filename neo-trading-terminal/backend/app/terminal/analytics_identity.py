"""Cross-check documented provider neoSymbol and explicit master identity fields.

Canonical grouping uses the broker's documented underlying code plus segment and
instrument class, not a parsed trading symbol. This is not cash-token, settlement
or exchange-timestamp verification.
"""
from decimal import Decimal
from datetime import date,datetime,UTC
from zoneinfo import ZoneInfo

from .catalogue import expiry_date
from .options_snapshot import expiry_identity


def eligible_contracts(chain,catalogue,quotes):
    if chain.get('exchange')!='nse_fo' or not all(chain.get('identity_verification',{}).get(key) is True for key in ('underlying','exchange','expiry')):
        return []
    now = datetime.now(UTC)
    expiry = expiry_identity(chain['expiry'])
    if date.fromisoformat(expiry)<=now.astimezone(ZoneInfo('Asia/Kolkata')).date():
        return []  # No assumed expiry-session closing time.
    age = (now-datetime.fromisoformat(chain['retrieved_at'])).total_seconds()
    if not 0<=age<=10:
        return []
    by_quote = {quote['contract_id']:quote for quote in quotes}
    out = []
    for row in chain['rows']:
        identifier = row.get('contract_id')
        if not identifier:
            continue
        matches = [item for item in catalogue if item.get('id')==identifier]
        if len(matches)>1:
            raise ValueError('Ambiguous explicit provider token')
        if not matches:
            continue
        item = matches[0]
        meta,raw = item.get('source_metadata',{}),item.get('identity_source_fields',{})
        if meta.get('source')!='kotak-scrip-master' or not raw:
            continue
        underlying = raw.get('pSymbolName')
        instrument_type = meta.get('pInstType')
        if instrument_type not in ('OPTIDX','OPTSTK'):
            continue
        if (raw.get('pExchSeg'),raw.get('pTrdSymbol'),raw.get('pOptionType'),underlying)!=(chain['exchange'],row['symbol'],'CE' if row['side']=='CALL' else 'PE',chain['underlying']):
            raise ValueError('Contradictory explicit master identity')
        if identifier!='nse_fo|'+str(raw.get('pSymbol')) or item.get('token')!=str(raw.get('pSymbol')):
            raise ValueError('Contradictory master token')
        if expiry_date(raw.get('lExpiryDate') or raw.get('pExpiryDate'),'nse_fo')!=expiry or Decimal(str(raw.get('dStrikePrice')))/100!=Decimal(str(row['strike'])):
            raise ValueError('Contradictory master contract terms')
        lot_text = meta.get('lLotSize')
        if not isinstance(lot_text,str) or not lot_text.isascii() or not lot_text.isdigit() or not 0<int(lot_text)<=100000:
            continue
        quote = by_quote.get(identifier)
        lot = int(lot_text)
        if chain.get('lot_size') is None:
            continue
        if chain['lot_size']!=lot:
            raise ValueError('Contradictory common and per-contract lot metadata')
        if quote is None or any(quote.get(key) is None for key in ('bid','ask','bid_quantity','ask_quantity')):
            continue
        if not 0<=(now-datetime.fromisoformat(quote['observed_at'])).total_seconds()<=10:
            continue
        if Decimal(quote['bid_quantity'])<lot or Decimal(quote['ask_quantity'])<lot:
            continue
        out.append(dict(contract_id=identifier,identity_verified=True,underlying_key=f'nse_fo:{instrument_type}:{underlying}',
            exchange='nse_fo',currency='INR',expiry=expiry,strike=str(row['strike']),option_type=row['side'],lot_size=lot))
    return out
