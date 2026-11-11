"""Performance on verified cash-flow-adjusted daily returns, never holdings history inference."""
import numpy as np


def portfolio_attribution(returns, *, benchmark=None, bank_benchmark=None, risk_free_annual=0.):
    names = ('sharpe','sortino','calmar','omega','ulcer_index','max_drawdown','max_drawdown_duration',
             'beta_nifty50','beta_niftybank','win_rate','profit_factor')
    result = dict.fromkeys(names)
    reasons = {}
    if len(returns)<30:
        return {**result,'unavailable_reasons':dict.fromkeys(names,'insufficient_verified_return_history')}
    r = np.asarray(returns,dtype=float)
    if not np.all(np.isfinite(r)) or np.any(r<=-1):
        raise ValueError('Invalid verified return series')
    excess = r-risk_free_annual/252
    std = np.std(excess,ddof=1)
    downside = np.sqrt(np.mean(np.minimum(excess,0)**2))
    nav = np.cumprod(1+r)
    nav_with_initial = np.concatenate(([1.],nav))
    dd = nav_with_initial/np.maximum.accumulate(nav_with_initial)-1
    mdd = -float(np.min(dd))
    duration = longest = 0
    for drawdown in dd:
        duration = duration+1 if drawdown<0 else 0
        longest = max(duration,longest)
    annual = float(nav[-1]**(252/len(r))-1)
    losses = -np.minimum(excess,0).sum()
    result.update(sharpe=float(np.mean(excess)/std*np.sqrt(252)) if std>0 else None,
                  sortino=float(np.mean(excess)/downside*np.sqrt(252)) if downside>0 else None,
                  calmar=annual/mdd if mdd>0 else None,omega=float(np.maximum(excess,0).sum()/losses) if losses>0 else None,
                  ulcer_index=float(np.sqrt(np.mean(dd**2))*100),max_drawdown=mdd,max_drawdown_duration=longest)
    for name,series in (('beta_nifty50',benchmark),('beta_niftybank',bank_benchmark)):
        if series is not None and len(series)==len(r):
            b = np.asarray(series,dtype=float)
            if not np.all(np.isfinite(b)):
                raise ValueError('Invalid aligned benchmark')
            if np.var(b,ddof=1)>0:
                result[name] = float(np.cov(r,b)[0,1]/np.var(b,ddof=1))
    for name,value in result.items():
        if value is None:
            reasons[name] = 'requires_complete_trade_history' if name in ('win_rate','profit_factor') else 'missing_input_or_zero_denominator'
    return {**result,'unavailable_reasons':reasons,'observations':len(r),'method':'verified-daily-returns.1'}


def hrp_weights(adjusted_prices, *, eligible_assets):
    """Eligibility supplied by verified cash-position metadata, never model choice."""
    selected = [key for key in adjusted_prices.columns if key in eligible_assets]
    excluded = [key for key in adjusted_prices.columns if key not in eligible_assets]
    if not selected:
        return dict(weights=None,reason='no_eligible_cash_assets',excluded_assets=excluded)
    prices = adjusted_prices[selected]
    values = prices.to_numpy(dtype=float)
    if len(prices)<30 or not prices.index.is_unique or not prices.index.is_monotonic_increasing or not prices.columns.is_unique or not np.all(np.isfinite(values)) or np.any(values<=0):
        raise ValueError('HRP requires aligned positive adjusted prices and at least 30 observations')
    if len(selected)==1:
        return dict(weights={selected[0]:1.},excluded_assets=excluded,method='long-only-cash-hrp.1')
    try:
        from pypfopt import HRPOpt
    except ImportError:
        return dict(weights=None,reason='hrp_dependency_unavailable',excluded_assets=excluded)
    weights = dict(HRPOpt(returns=prices.pct_change(fill_method=None).dropna()).optimize())
    if any(not np.isfinite(w) or w<0 for w in weights.values()) or abs(sum(weights.values())-1)>1e-6:
        raise ValueError('Invalid HRP output')
    return dict(weights=weights,excluded_assets=excluded,method='long-only-cash-hrp.1')
