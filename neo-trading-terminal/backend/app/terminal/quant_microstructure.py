"""Deterministic returned-chain summaries; coverage is never inferred complete."""
import math
from .quant_pricing import black76


def gamma_exposure_proxy(rows,spot,sign_assumption):
    """Hypothetical signed OI proxy in INR hedge notional per one-percent spot move.

    Forward shocks are proportional to spot, holding carry and IV fixed. Inventory
    signs are an explicit scenario, never inferred dealer ownership.
    """
    if sign_assumption!='calls_positive_puts_negative' or not rows or len(rows)>500 or not math.isfinite(float(spot)) or spot<=0:
        raise ValueError('Explicit bounded GEX assumptions required')
    def exposure(level):
        total = 0.
        for row in rows:
            f = float(row['forward'])*level/spot
            gamma = black76(f,row['strike'],row['tau'],row['iv'],row['rate'],row['side'])['gamma_forward']
            if gamma is None:
                raise ValueError('Positive time and IV required for GEX')
            oi,lot = row['open_interest'],row['lot_size']
            if type(oi) is not int or oi<0 or type(lot) is not int or lot<=0:
                raise ValueError('Explicit contract-count OI and multiplier required')
            total += (1 if row['side']=='CALL' else -1)*gamma*(f/level)**2*oi*lot*level**2*.01
        if not math.isfinite(total):
            raise ValueError('Nonfinite GEX scenario')
        return total
    grid = [(spot*(.8+i*.005),0.) for i in range(81)]
    grid = [(level,exposure(level)) for level,_ in grid]
    flips = []
    for index in range(1,len(grid)-1):
        if grid[index][1]==0 and grid[index-1][1]*grid[index+1][1]<0:
            flips.append(grid[index][0])
    for (a,x),(b,y) in zip(grid,grid[1:]):
        if x*y<0:
            for _ in range(32):
                mid=(a+b)/2
                value=exposure(mid)
                if x*value<=0: b=mid
                else: a,x=mid,value
            flips.append((a+b)/2)
    return dict(dealer_gex_proxy=exposure(spot),zero_gamma_flip=min(flips,key=lambda x:abs(x-spot)) if flips else None,
        gamma_flip_candidates=flips,gex_units='INR_hedge_notional_per_1pct_spot_move',gex_sign_assumption=sign_assumption,
        gex_coverage='supplied_contracts_only',limitations=['Hypothetical signed-OI proxy; dealer inventory is unknown. Fixed IV/carry, proportional forward shocks; flip search limited to 80–120 percent of supplied spot.'])


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
