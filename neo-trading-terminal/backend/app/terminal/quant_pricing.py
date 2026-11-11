"""Pure Black-76 forward pricing. IV is a fraction, time is ACT/365 years.

Derivatives hold the forward and continuously compounded discount rate fixed.
Never substitute option LTP for an underlying forward or infer absent rates.
"""
import math


def _cdf(x):
    return .5 * math.erfc(-x / math.sqrt(2))


def black76(forward, strike, tau, iv, rate, option_type):
    f, k, t, s, r = map(float, (forward, strike, tau, iv, rate))
    if not all(math.isfinite(x) for x in (f,k,t,s,r)) or f <= 0 or k <= 0 or t < 0 or s < 0 or option_type not in ('CALL','PUT'):
        raise ValueError('Invalid Black76 inputs')
    sign = 1 if option_type == 'CALL' else -1
    discount = math.exp(-r*t)
    if t == 0 or s == 0:
        return dict(price=discount*max(sign*(f-k),0), delta_forward=None, gamma_forward=None,
                    theta_calendar_day=None, theta_calendar_hour=None, vega_per_pct=None,
                    vega_per_unit=None, rho=None, vanna=None, volga=None, charm=None)
    root = math.sqrt(t)
    d1 = math.log(f/k)/(s*root)+.5*s*root
    d2 = d1-s*root
    density = math.exp(-d1*d1/2)/math.sqrt(2*math.pi)
    price = discount*sign*(f*_cdf(sign*d1)-k*_cdf(sign*d2))
    delta = discount*sign*_cdf(sign*d1)
    vega = discount*f*density*root
    theta = r*price-discount*f*density*s/(2*root)
    d1_dt = -math.log(f/k)/(2*s*t*root)+s/(4*root)
    return dict(price=price, delta_forward=delta, gamma_forward=discount*density/(f*s*root),
                theta_calendar_day=theta/365, theta_calendar_hour=theta/(365*24),
                vega_per_pct=vega*.01, vega_per_unit=vega, rho=-t*price,
                vanna=-discount*density*d2/s, volga=vega*d1*d2/s,
                charm=r*delta-discount*density*d1_dt)


def implied_volatility(price, forward, strike, tau, rate, option_type):
    price = float(price)
    if not math.isfinite(price) or price < 0 or tau <= 0:
        raise ValueError('Invalid IV inputs')
    low, high = 1e-9, 8.0
    floor = black76(forward,strike,tau,0,rate,option_type)['price']
    ceiling = black76(forward,strike,tau,high,rate,option_type)['price']
    if price < floor or price >= ceiling:
        return None
    if abs(price-floor) < 1e-12:
        return 0.0
    for _ in range(100):
        mid = (low+high)/2
        if black76(forward,strike,tau,mid,rate,option_type)['price'] < price:
            low = mid
        else:
            high = mid
    return (low+high)/2
