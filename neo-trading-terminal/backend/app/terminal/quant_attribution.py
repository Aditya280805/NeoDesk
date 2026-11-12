"""Performance on verified cash-flow-adjusted daily returns, never holdings history inference."""
import numpy as np

# Daily fractional-return standard deviations below one part per billion are
# treated as numerically degenerate; do not turn rounding noise into risk ratios.
RETURN_STD_FLOOR = 1e-9


def portfolio_attribution(returns, *, benchmark=None, bank_benchmark=None, risk_free_annual=0.):
    names = ('sharpe','sortino','calmar','omega','ulcer_index','max_drawdown','max_drawdown_duration',
             'beta_nifty50','beta_niftybank','alpha_nifty50_annualized','alpha_niftybank_annualized','win_rate','profit_factor')
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
    result.update(sharpe=float(np.mean(excess)/std*np.sqrt(252)) if std>RETURN_STD_FLOOR else None,
                  sortino=float(np.mean(excess)/downside*np.sqrt(252)) if downside>RETURN_STD_FLOOR else None,
                  calmar=annual/mdd if mdd>0 else None,omega=float(np.maximum(excess,0).sum()/losses) if losses>0 else None,
                  ulcer_index=float(np.sqrt(np.mean(dd**2))*100),max_drawdown=mdd,max_drawdown_duration=longest)
    for name,series in (('beta_nifty50',benchmark),('beta_niftybank',bank_benchmark)):
        if series is not None and len(series)==len(r):
            b = np.asarray(series,dtype=float)
            if not np.all(np.isfinite(b)):
                raise ValueError('Invalid aligned benchmark')
            if np.var(b,ddof=1)>RETURN_STD_FLOOR**2:
                result[name] = float(np.cov(r,b)[0,1]/np.var(b,ddof=1))
                result[name.replace('beta_','alpha_')+'_annualized'] = float((np.mean(excess)-result[name]*np.mean(b-risk_free_annual/252))*252)
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
    returns = prices.pct_change(fill_method=None).dropna()
    variances = returns.var()
    if not np.all(np.isfinite(variances)) or (variances<=RETURN_STD_FLOOR**2).any():
        return dict(weights=None,reason='zero_variance_cash_returns',excluded_assets=excluded)
    try:
        from pypfopt import HRPOpt
    except ImportError:
        return dict(weights=None,reason='hrp_dependency_unavailable',excluded_assets=excluded)
    weights = dict(HRPOpt(returns=returns).optimize())
    if any(not np.isfinite(w) or w<0 for w in weights.values()) or abs(sum(weights.values())-1)>1e-6:
        raise ValueError('Invalid HRP output')
    return dict(weights=weights,excluded_assets=excluded,method='long-only-cash-hrp.1')


def declared_attribution(bundle):
    """User-declared scenario coverage; never verifies assets, fills or adjustments."""
    import pandas as pd
    assets,trades = bundle['assets'],bundle['trades']
    cash = [asset for asset in assets if asset['kind'] in ('cash_equity','cash_etf')]
    eligible = {asset['asset_id'] for asset in cash}
    result = dict(hrp_weights=None,sector_allocation=None,cash_asset_hhi=None,cash_sector_hhi=None,cash_correlation_matrix=None,hrp_coverage={'excluded_assets':[]},unavailable_reasons={})
    if assets:
        prices = pd.DataFrame({asset['asset_id']:asset['adjusted_prices'] for asset in assets},index=bundle['dates'])
        selected = prices[[key for key in prices.columns if key in eligible]]
        variances = selected.pct_change(fill_method=None).dropna().var()
        nondegenerate = [key for key in selected if np.isfinite(variances[key]) and variances[key]>RETURN_STD_FLOOR**2]
        if nondegenerate:
            result['cash_correlation_matrix'] = selected[nondegenerate].pct_change(fill_method=None).dropna().corr().to_dict()
        result['correlation_coverage'] = dict(basis='declared_adjusted_daily_cash_price_returns',observations=max(0,len(prices)-1),excluded_assets=[key for key in prices if key not in nondegenerate])
        if len(selected.columns)>1 and (not np.all(np.isfinite(variances)) or (variances<=RETURN_STD_FLOOR**2).any()):
            hrp = dict(weights=None,reason='zero_variance_cash_returns',excluded_assets=[key for key in prices.columns if key not in eligible])
        else:
            hrp = hrp_weights(prices,eligible_assets=eligible)
        result.update(hrp_weights=hrp.pop('weights'),hrp_coverage={**hrp,'eligibility_basis':'user_declared_asset_kind'})
        total = sum(asset['value_paise'] for asset in cash)
        if total:
            sectors = {}
            for asset in cash:
                key = asset['sector'] or 'UNCLASSIFIED'
                sectors[key] = sectors.get(key,0)+asset['value_paise']/total
            result['sector_allocation'] = sectors
            result['cash_asset_hhi'] = sum((asset['value_paise']/total)**2 for asset in cash)
            result['cash_sector_hhi'] = sum(weight**2 for weight in sectors.values())
    if bundle['trade_history_complete'] and trades:
        profits = sum(max(0,trade['net_pnl_paise']) for trade in trades)
        losses = sum(max(0,-trade['net_pnl_paise']) for trade in trades)
        result.update(win_rate=sum(trade['net_pnl_paise']>0 for trade in trades)/len(trades),
            profit_factor=profits/losses if losses else None,closed_trade_count=len(trades))
        if not losses:
            result['unavailable_reasons']['profit_factor']='no_realized_loss_denominator'
    else:
        result['unavailable_reasons'].update(win_rate='complete_closed_trade_history_required',profit_factor='complete_closed_trade_history_required')
    result['trade_coverage'] = dict(period_start=bundle.get('trade_period_start'),period_end=bundle.get('trade_period_end'),
        completeness='user_declared_complete' if bundle['trade_history_complete'] else 'partial',closed_trade_count=len(trades))
    result['limitations'] = ['Cash-only HRP and sector allocation cover declared assets; derivatives excluded. Sector allocation is not sector performance attribution. Trade P&L and completeness are user declarations.']
    return result
