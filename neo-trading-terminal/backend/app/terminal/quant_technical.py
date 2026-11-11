"""TA-Lib reference calculations with an explicitly limited NumPy fallback."""
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np

from .analytics_contracts import sanitize_quant_payload


def _ema(values, period):
    out = np.full(len(values),np.nan)
    if len(values)>=period:
        out[period-1] = np.mean(values[:period])
        for i in range(period,len(values)):
            out[i] = out[i-1]+2/(period+1)*(values[i]-out[i-1])
    return out


def technical_regime(bars, *, vix_history=(), backend='auto'):
    if not 1 <= len(bars) <= 500 or backend not in ('auto','numpy','talib'):
        raise ValueError('Invalid technical request')
    arrays = {k:np.array([r[k] for r in bars],dtype=float) for k in ('open','high','low','close')}
    o,h,l,c = (arrays[k] for k in ('open','high','low','close'))
    if any(not np.all(np.isfinite(v)) for v in arrays.values()) or np.any(l<=0) or np.any(h<l) or np.any(c>h) or np.any(c<l) or np.any(o>h) or np.any(o<l):
        raise ValueError('Invalid OHLC bars')
    metrics = {k:None for k in ('ema20','ema50','ema200','adx14','plus_di14','minus_di14','sar','rsi14',
        'macd','macd_signal','macd_hist_slope','stoch_k','stoch_d','cci14','atr14','natr14',
        'bbands_width','bbands_width_percentile20','vwap','obv_slope','mfi14','india_vix','vix_zscore20')}
    last = lambda a: float(a[-1]) if len(a) and np.isfinite(a[-1]) else None
    for p in (20,50,200):
        metrics[f'ema{p}'] = last(_ema(c,p))
    width = np.full(len(c),np.nan)
    for i in range(19,len(c)):
        window = c[i-19:i+1]
        width[i] = 4*np.std(window)/np.mean(window)
    metrics['bbands_width'] = last(width)
    if len(c)>=39:
        metrics['bbands_width_percentile20'] = float(np.mean(width[-20:]<=width[-1])*100)
    talib = None
    if backend != 'numpy':
        try:
            import talib
        except ImportError:
            if backend == 'talib':
                raise ValueError('TA-Lib backend unavailable') from None
    patterns = None
    volume = None
    if all(r.get('volume') is not None for r in bars):
        volume = np.array([r['volume'] for r in bars],dtype=float)
        if not np.all(np.isfinite(volume)) or np.any(volume<0):
            raise ValueError('Invalid volume')
    if talib is not None:
        for name,fn,args in (
            ('adx14',talib.ADX,(h,l,c)),('plus_di14',talib.PLUS_DI,(h,l,c)),('minus_di14',talib.MINUS_DI,(h,l,c)),
            ('sar',talib.SAR,(h,l)),('rsi14',talib.RSI,(c,)),('cci14',talib.CCI,(h,l,c)),
            ('atr14',talib.ATR,(h,l,c)),('natr14',talib.NATR,(h,l,c))):
            metrics[name] = last(fn(*args))
        line,signal,hist = talib.MACD(c)
        metrics.update(macd=last(line),macd_signal=last(signal),macd_hist_slope=last(np.diff(hist)))
        k,d = talib.STOCH(h,l,c,fastk_period=14,slowk_period=3,slowd_period=3)
        metrics.update(stoch_k=last(k),stoch_d=last(d))
        patterns = {name:int(getattr(talib,name)(o,h,l,c)[-1]) for name in
                    ('CDLENGULFING','CDLHAMMER','CDLSHOOTINGSTAR','CDLDOJI','CDLMORNINGSTAR','CDLEVENINGSTAR')} if len(c)>=15 else None
        if volume is not None:
            metrics.update(obv_slope=last(np.diff(talib.OBV(c,volume))),mfi14=last(talib.MFI(h,l,c,volume)))
    if volume is not None and all(r.get('time') for r in bars):
        times = [datetime.fromisoformat(str(r['time']).replace('Z','+00:00')) for r in bars]
        if any(t.tzinfo is None for t in times) or any(a>=b for a,b in zip(times,times[1:])):
            raise ValueError('Bars must be ordered timezone-aware observations')
        session = times[-1].astimezone(ZoneInfo('Asia/Kolkata')).date()
        mask = np.array([t.astimezone(ZoneInfo('Asia/Kolkata')).date()==session for t in times])
        total = volume[mask].sum()
        metrics['vwap'] = float(np.sum(((h+l+c)/3)[mask]*volume[mask])/total) if total>0 else None
    if vix_history:
        v = np.array(vix_history,dtype=float)
        if not np.all(np.isfinite(v)) or np.any(v<=0):
            raise ValueError('Invalid VIX history')
        metrics['india_vix'] = float(v[-1])
        if len(v)>=20 and np.std(v[-20:])>0:
            metrics['vix_zscore20'] = float((v[-1]-np.mean(v[-20:]))/np.std(v[-20:]))
    adx,z,pct = (metrics[k] for k in ('adx14','vix_zscore20','bbands_width_percentile20'))
    regime = 'UNAVAILABLE'
    if all(x is not None for x in (adx,z,pct)):
        regime = 'HIGH_VOL_BREAKOUT' if adx>=25 and z>.5 else 'LOW_VOL_TREND' if adx>=25 else 'HIGH_VOL_MEAN_REVERTING' if adx<22 and z>.5 else 'LOW_VOL_RANGE' if adx<20 and pct<50 and z<=.5 else 'TRANSITIONAL'
    return sanitize_quant_payload(dict(metrics=metrics,patterns=patterns,regime=regime,backend='talib' if talib else 'numpy-subset',
        unavailable_reasons={k:'insufficient_history_or_required_input_or_backend' for k,v in metrics.items() if v is None}))
