"""Effective-dated statutory components; exchange/broker costs require a schedule.

Amounts are INR Decimal inputs. Outputs are paise, rounded per component using
HALF_UP. These are estimates until reconciled with contract-note aggregation.
"""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP


def statutory_charges(product, side, turnover_inr, trade_date, *, brokerage_inr=0,
                      exchange_rate=None, sebi_rate=None, slippage_inr=None):
    if product not in ('option','future','delivery','intraday') or side not in ('BUY','SELL','EXERCISE'):
        raise ValueError('Unsupported fee transaction')
    if side == 'EXERCISE' and product != 'option':
        raise ValueError('Exercise requires an option intrinsic turnover')
    day = date.fromisoformat(trade_date) if isinstance(trade_date,str) else trade_date
    if day < date(2024,10,1):
        raise ValueError('No verified schedule for this date')
    def amount(x):
        value = Decimal(str(x))
        if not value.is_finite() or value < 0:
            raise ValueError('Fee inputs must be finite and nonnegative')
        return value
    turnover, brokerage = amount(turnover_inr), amount(brokerage_inr)
    modern = day >= date(2026,4,1)
    stt = Decimal(0)
    if product == 'option':
        stt = Decimal('.0015' if modern else '.00125' if side == 'EXERCISE' else '.001') if side != 'BUY' else Decimal(0)
    elif product == 'future' and side == 'SELL':
        stt = Decimal('.0005' if modern else '.0002')
    elif product == 'delivery':
        stt = Decimal('.001')
    elif product == 'intraday' and side == 'SELL':
        stt = Decimal('.00025')
    stamp = Decimal({'option':'.00003','future':'.00002','delivery':'.00015','intraday':'.00003'}[product]) if side == 'BUY' else Decimal(0)
    exchange = turnover*amount(exchange_rate) if exchange_rate is not None and side != 'EXERCISE' else None
    sebi = turnover*amount(sebi_rate) if sebi_rate is not None and side != 'EXERCISE' else None
    gst = (brokerage+exchange+sebi)*Decimal('.18') if exchange is not None and sebi is not None else None
    paise = lambda x: None if x is None else int((x*100).quantize(Decimal(1),rounding=ROUND_HALF_UP))
    result = dict(stt_paise=paise(turnover*stt),stamp_paise=paise(turnover*stamp),
                  brokerage_paise=paise(brokerage),exchange_paise=paise(exchange),sebi_paise=paise(sebi),
                  gst_paise=paise(gst),slippage_paise=paise(amount(slippage_inr)) if slippage_inr is not None else None,
                  schedule_version='stt.2026-04-01' if modern else 'stt.2024-10-01',
                  itm_expiry_stt_trap_warning=side == 'EXERCISE',
                  status='ESTIMATE',rounding='component-paise-half-up; contract-note aggregation unverified')
    components = [result[k] for k in ('stt_paise','stamp_paise','brokerage_paise','exchange_paise','sebi_paise','gst_paise','slippage_paise')]
    result['total_paise'] = sum(components) if all(x is not None for x in components) else None
    return result
