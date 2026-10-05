"""Indicators and a deterministic long-only next-bar-open backtest."""
def sma(values, period):
    return [None if i+1<period else sum(values[i-period+1:i+1])/period for i in range(len(values))]


def indicators(candles, period=14):
    closes = [c['close'] for c in candles]
    rsi = [None] * len(closes)
    if len(closes) > period:
        moves = [closes[i]-closes[i-1] for i in range(1,len(closes))]
        gain = sum(max(m,0) for m in moves[:period])/period
        loss = sum(max(-m,0) for m in moves[:period])/period
        for i in range(period,len(closes)):
            if i>period:
                delta=closes[i]-closes[i-1]
                gain=(gain*(period-1)+max(delta,0))/period
                loss=(loss*(period-1)+max(-delta,0))/period
            rsi[i] = 50 if gain == loss == 0 else 100 if loss == 0 else 100-100/(1+gain/loss)
    return {'sma20':sma(closes,20), 'sma50':sma(closes,50), 'sma200':sma(closes,200), 'rsi14':rsi}


def backtest(candles, initial, fast=20, slow=50, fee_bps=5, slippage_bps=5):
    if fast >= slow or len(candles) < slow+2:
        raise ValueError('Fast period must be below slow period, with enough candles for warm-up.')
    closes=[c['close'] for c in candles]
    f,s=sma(closes,fast),sma(closes,slow)
    cash, held, peak, drawdown = float(initial),0,float(initial),0.0
    trades, curve = [],[]
    fee, slip=fee_bps/10000,slippage_bps/10000
    for i in range(slow,len(candles)):
        # Only data known at the preceding close can trigger this open's trade.
        want = f[i-1]>s[i-1]
        if want and held==0:
            price=candles[i]['open']*(1+slip)
            held=int(cash/(price*(1+fee)))
            if held:
                cash-=held*price*(1+fee)
                trades.append({'time':candles[i]['time'],'side':'BUY','quantity':held,'price':round(price,2)})
        elif not want and held:
            price=candles[i]['open']*(1-slip)
            cash+=held*price*(1-fee)
            trades.append({'time':candles[i]['time'],'side':'SELL','quantity':held,'price':round(price,2)})
            held=0
        equity=cash+held*candles[i]['close']
        peak=max(peak,equity)
        drawdown=max(drawdown,(peak-equity)/peak*100)
        curve.append({'time':candles[i]['time'],'value':round(equity,2)})
    return {'initial':initial,'ending_equity':round(equity,2),'return_pct':round((equity/initial-1)*100,2),
            'max_drawdown_pct':round(drawdown,2),'trades':trades,'curve':curve,'open_quantity':held,
            'model':'Long-only SMA crossover; preceding-close signal, next-bar-open fills. Final holdings marked at last close. Costs are illustrative; taxes and liquidity are not modeled.'}
