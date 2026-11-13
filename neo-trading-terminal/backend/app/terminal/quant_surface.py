"""Surface summaries from verified expiry timestamps and explicit pricing inputs."""
import math
from .quant_pricing import black76, implied_volatility


def volatility_surface(rows, *, forward, rate, as_of, iv_history=(), realized_volatility=None, pricing_by_expiry=None):
    if as_of.tzinfo is None or len(rows)>1000:
        raise ValueError('Invalid surface request')
    if len({r['expiry_at'] for r in rows})>1 and pricing_by_expiry is None:
        raise ValueError('Per-expiry forward and discount inputs required')
    out = []
    for r in rows:
        expiry = r['expiry_at']
        if expiry.tzinfo is None:
            raise ValueError('Actual exchange expiry timestamp required')
        tau = max(0,(expiry-as_of).total_seconds()/(365*86400))
        f,risk_rate = forward,rate
        if pricing_by_expiry is not None:
            inputs = pricing_by_expiry.get(expiry.isoformat())
            if not inputs:
                raise ValueError('Missing per-expiry pricing inputs')
            f,risk_rate = inputs['forward'],inputs['rate']
        iv = r.get('iv')
        if iv is None and r.get('premium') is not None and tau>0:
            iv = implied_volatility(r['premium'],f,r['strike'],tau,risk_rate,r['side'])
        greeks = black76(f,r['strike'],tau,iv,risk_rate,r['side']) if iv is not None else None
        out.append(dict(contract_id=r['contract_id'],strike=float(r['strike']),side=r['side'],expiry_at=expiry.isoformat(),
                        tau=tau,iv=iv,greeks=greeks,forward=f))
    active = [r for r in out if r['tau']>0 and r['iv'] is not None]
    near = min((r['tau'] for r in active),default=None)
    nearest = [r for r in active if r['tau']==near]
    atm = min(nearest,key=lambda r:abs(r['strike']-r['forward']))['iv'] if nearest else None
    history = list(map(float,iv_history))
    if any(not math.isfinite(x) or x<=0 for x in history):
        raise ValueError('Invalid historical IV')
    rank = percentile = None
    if atm is not None and len(history)>=252:
        window = history[-252:]
        rank = (atm-min(window))/(max(window)-min(window))*100 if max(window)>min(window) else None
        percentile = sum(x<=atm for x in window)/252*100
    # Interpolate only within observed forward-delta wings; never extrapolate.
    def wing(side,delta):
        points = sorted((abs(r['greeks']['delta_forward']),r['iv']) for r in nearest if r['side']==side and r['greeks'] and r['greeks']['delta_forward'] is not None)
        for (a,x),(b,y) in zip(points,points[1:]):
            if a<=delta<=b and b>a:
                return x+(y-x)*(delta-a)/(b-a)
        return None
    put,call = wing('PUT',.25),wing('CALL',.25)
    expiries = sorted({r['tau'] for r in active})
    next_atm = min((r for r in active if len(expiries)>1 and r['tau']==expiries[1]),key=lambda r:abs(r['strike']-r['forward']),default=None)
    return dict(rows=out,atm_iv=atm,iv_rank_252d=rank,iv_percentile_252d=percentile,
                iv_rv_spread=atm-realized_volatility if atm is not None and realized_volatility is not None else None,
                risk_reversal_25d=put-call if put is not None and call is not None else None,
                butterfly_25d=(put+call)/2-atm if put is not None and call is not None and atm is not None else None,
                term_structure_slope=next_atm['iv']-atm if next_atm and atm is not None else None,
                limitations=['Forward delta convention; IV fractions; no wing extrapolation.'])
