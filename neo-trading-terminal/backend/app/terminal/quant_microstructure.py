"""Deterministic returned-chain summaries; coverage is never inferred complete."""
import math


def oi_microstructure(rows):
    if len(rows)>1000:
        raise ValueError('Chain too large')
    enriched = []
    def number(value):
        if value is None:
            return None
        result = float(value)
        if not math.isfinite(result) or result < 0:
            raise ValueError('Invalid chain value')
        return result
    for row in rows:
        if row.get('side') not in ('CALL','PUT'):
            raise ValueError('Unknown option side')
        strike = number(row['strike'])
        oi,prev = number(row.get('open_interest')),number(row.get('previous_open_interest'))
        price,prior = number(row.get('ltp')),number(row.get('previous_price'))
        delta_oi = oi-prev if oi is not None and prev is not None else None
        delta_p = price-prior if price is not None and prior is not None else None
        tag = None
        if delta_oi and delta_p:
            tag = ('LONG_BUILDUP' if delta_p>0 else 'SHORT_BUILDUP') if delta_oi>0 else ('SHORT_COVERING' if delta_p>0 else 'LONG_UNWINDING')
        enriched.append(dict(side=row['side'],strike=strike,open_interest=oi,volume=number(row.get('volume')),delta_oi=delta_oi,buildup=tag))
    calls = [r for r in enriched if r['side']=='CALL']
    puts = [r for r in enriched if r['side']=='PUT']
    def ratio(field):
        if not calls or not puts or any(r[field] is None for r in enriched):
            return None
        denominator = sum(r[field] for r in calls)
        return sum(r[field] for r in puts)/denominator if denominator else None
    strikes = sorted({r['strike'] for r in enriched})
    pain = None
    if calls and puts and all(r['open_interest'] is not None for r in enriched):
        pain = min(strikes,key=lambda s:sum(r['open_interest']*max((s-r['strike']) if r['side']=='CALL' else (r['strike']-s),0) for r in enriched))
    walls = lambda group: sorted([r for r in group if r['open_interest'] is not None],key=lambda r:(-r['open_interest'],r['strike']))[:3]
    return dict(rows=enriched,pcr_oi=ratio('open_interest'),pcr_volume=ratio('volume'),max_pain_strike=pain,
                call_walls=walls(calls),put_walls=walls(puts),dealer_gex_proxy=None,zero_gamma_flip=None,
                coverage='returned_strikes_only',limitations=['Dealer inventory and complete-chain coverage are not inferred.'])
