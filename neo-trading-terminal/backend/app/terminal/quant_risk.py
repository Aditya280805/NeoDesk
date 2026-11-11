"""Full repricing stress and empirical loss tails, deliberately independent."""
import math
from .quant_pricing import black76


def historical_tail(losses):
    values = []
    for x in losses:
        if isinstance(x, bool) or not math.isfinite(float(x)):
            raise ValueError('Historical losses must be finite and validated')
        values.append(float(x))
    values.sort()
    n = len(values)
    result = {'scenario_count': n, 'method': 'empirical-inverse-cdf-fractional-tail.v1', 'unavailable_reasons': {}}
    for label, probability, minimum in (('95',.95,250),('99',.99,1000)):
        if n < minimum:
            for metric in ('var','cvar'):
                result[f'{metric}_{label}'] = None
                result['unavailable_reasons'][f'{metric}_{label}'] = f'insufficient_history_for_{label}pct'
            continue
        result[f'var_{label}'] = values[math.ceil(probability*n)-1]
        # Integrate the empirical quantile function over the worst 1-p mass.
        mass = n*(1-probability)
        whole = int(math.floor(mass+1e-10))
        fraction = max(0.,mass-whole)
        total = sum(values[-whole:]) if whole else 0.
        if fraction > 1e-10:
            total += fraction*values[n-whole-1]
        result[f'cvar_{label}'] = total/mass
    return result


def stress_matrix(positions, historical_losses=()):
    if len(positions) > 1000:
        raise ValueError('Position limit exceeded')
    def value(row, spot_shock=0., vol_shock=0., elapsed=0.):
        quantity = float(row['quantity'])
        if row['kind'] in ('equity','future'):
            return quantity*float(row['spot'])*(1+spot_shock)
        return quantity*black76(float(row['forward'])*(1+spot_shock), row['strike'],
            max(0,float(row['tau'])-elapsed),float(row['iv'])*(1+vol_shock),row['rate'],row['option_type'])['price']
    base = sum(value(r) for r in positions)
    cells = []
    for spot in (-.05,-.03,-.015,0.,.015,.03,.05):
        for vol in (-.2,0.,.25,.5):
            pnl = sum(value(r,spot,vol,1/365) for r in positions)-base
            cells.append(dict(spot_shock=spot, iv_relative_shock=vol,pnl=pnl))
    worst = min(cells,key=lambda x:x['pnl'])
    return dict(cells=cells,worst_case_scenario=worst,max_stress_loss=max(0,-worst['pnl']),
                historical_tail=historical_tail(historical_losses),post_shock_margin_deficit_paise=None,
                risk_verdict='CANNOT_ASSESS',
                limitations=['Parallel proportional VIX-to-IV scenario assumption; fixed carry.',
                             'Stress losses are not exchange margin. Historical losses require independently validated repricing scenarios.'])
