"""Full repricing stress and empirical loss tails, deliberately independent."""
import math
from datetime import date
from .quant_pricing import black76


def historical_repricing(positions, history_by_contract):
    """Apply aligned historical spot/contract-IV relative moves to current marks.

    Source adapters must validate trading-session coverage and corporate actions.
    Each pair uses its actual calendar elapsed days for option time decay.
    Incomplete series lose only affected scenarios; portfolio uses their intersection.
    """
    stress_matrix(positions)  # Validate current inputs with the same pricing contract.
    if sum(len(v) for v in history_by_contract.values())>100000:
        raise ValueError('Historical scenario budget exceeded')
    instruments, losses_by_horizon = {}, {1:[],5:[]}
    for row in positions:
        identifier = row['contract_id']
        if identifier in instruments:
            raise ValueError('Duplicate contract positions must be normalized')
        series = history_by_contract.get(identifier,[])
        if len(series)>5000:
            raise ValueError('Historical series too large')
        parsed = []
        for observation in series:
            day = date.fromisoformat(observation['date'])
            session = observation['session']
            if type(session) is not int or parsed and (day<=parsed[-1][0] or session!=parsed[-1][1]+1):
                raise ValueError('Historical observations must be ordered consecutive sessions')
            parsed.append((day,session,observation))
        instruments[identifier] = {}
        quantity = float(row['quantity'])
        option = row['kind']=='option'
        base = quantity*(black76(row['forward'],row['strike'],row['tau'],row['iv'],row['rate'],row['option_type'])['price'] if option else float(row['spot']))
        for horizon in (1,5):
            losses = {}
            for i in range(horizon,len(parsed)):
                start,_,a = parsed[i-horizon]
                end,_,b = parsed[i]
                required = ('spot','iv') if option else ('spot',)
                values = [x.get(k) for x in (a,b) for k in required]
                if any(v is None for v in values):
                    continue
                if any(isinstance(v,bool) or not math.isfinite(float(v)) or float(v)<=0 for v in values):
                    raise ValueError('Invalid historical repricing input')
                spot_ratio = float(b['spot'])/float(a['spot'])
                if option:
                    mark = black76(float(row['forward'])*spot_ratio,row['strike'],max(0,float(row['tau'])-(end-start).days/365),
                                   float(row['iv'])*float(b['iv'])/float(a['iv']),row['rate'],row['option_type'])['price']
                else:
                    mark = float(row['spot'])*spot_ratio
                losses[(start,end)] = base-quantity*mark
            instruments[identifier][f'{horizon}d'] = historical_tail(losses.values())
            losses_by_horizon[horizon].append(losses)
    portfolio = {}
    for horizon,series in losses_by_horizon.items():
        common = set.intersection(*(set(s) for s in series)) if series else set()
        portfolio[f'{horizon}d'] = historical_tail([sum(s[key] for s in series) for key in sorted(common)])
    return dict(instruments=instruments,portfolio=portfolio,method='historical-full-repricing.1',
                limitations=['Current positions held constant; empirical overlapping horizons; fixed carry and proportional forward shock.'])


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
    if not positions or len(positions) > 1000:
        raise ValueError('Position limit exceeded')
    for row in positions:
        if row.get('kind') not in ('equity','future','option'):
            raise ValueError('Unknown stress instrument kind')
        for field in ('quantity','spot'):
            value = row.get(field)
            if isinstance(value,bool) or value is None or not math.isfinite(float(value)) or field == 'spot' and float(value)<=0:
                raise ValueError('Invalid stress position input')
        if row['kind']=='option':
            black76(row['forward'],row['strike'],row['tau'],row['iv'],row['rate'],row['option_type'])
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
