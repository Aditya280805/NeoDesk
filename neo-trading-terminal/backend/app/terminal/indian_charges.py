"""Effective-dated statutory components; exchange/broker costs require a schedule.

Amounts are INR Decimal inputs. Outputs are paise, rounded per component using
HALF_UP. These are estimates until reconciled with contract-note aggregation.
"""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP


def statutory_charges(product, side, turnover_inr, trade_date, *, brokerage_inr=0,
                      exchange_rate=None, sebi_rate=None, slippage_inr=None,
                      exercise_charge_inr=None):
    if product not in ('option', 'future', 'delivery', 'intraday') or side not in ('BUY', 'SELL', 'EXERCISE', 'ASSIGNMENT'):
        raise ValueError('Unsupported fee transaction')
    if side in ('EXERCISE', 'ASSIGNMENT') and product != 'option':
        raise ValueError('Exercise requires an option intrinsic turnover')
    day = date.fromisoformat(trade_date) if isinstance(trade_date, str) else trade_date
    if day < date(2024, 10, 1):
        raise ValueError('No verified schedule for this date')
    def amount(x):
        value = Decimal(str(x))
        if not value.is_finite() or value < 0:
            raise ValueError('Fee inputs must be finite and nonnegative')
        return value

    turnover = amount(turnover_inr)
    brokerage = amount(brokerage_inr) if brokerage_inr is not None else None
    exercise_charge = amount(exercise_charge_inr) if exercise_charge_inr is not None else None

    modern = day >= date(2026, 4, 1)
    stt = Decimal(0)
    if product == 'option':
        if side in ('EXERCISE', 'ASSIGNMENT'):
            stt = Decimal('.0015' if modern else '.00125')
        elif side == 'SELL':
            stt = Decimal('.0015' if modern else '.001')
        else:
            stt = Decimal(0)
    elif product == 'future' and side == 'SELL':
        stt = Decimal('.0005' if modern else '.0002')
    elif product == 'delivery':
        stt = Decimal('.001')
    elif product == 'intraday' and side == 'SELL':
        stt = Decimal('.00025')

    stamp = Decimal({'option': '.00003', 'future': '.00002', 'delivery': '.00015', 'intraday': '.00003'}[product]) if side == 'BUY' else Decimal(0)
    exchange = turnover * amount(exchange_rate) if exchange_rate is not None and side not in ('EXERCISE', 'ASSIGNMENT') else None
    sebi = turnover * amount(sebi_rate) if sebi_rate is not None and side not in ('EXERCISE', 'ASSIGNMENT') else None

    paise = lambda x: None if x is None else int((x * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))

    # GST is 18% on (Brokerage + Exchange + SEBI + Exercise Charge)
    gst = None
    if brokerage is not None:
        gst_base = brokerage + (exercise_charge or Decimal(0))
        if side in ('EXERCISE', 'ASSIGNMENT'):
            gst = gst_base * Decimal('.18')
        elif exchange is not None and sebi is not None:
            gst = (gst_base + exchange + sebi) * Decimal('.18')

    result = dict(
        stt_paise=paise(turnover * stt),
        stamp_paise=paise(turnover * stamp),
        brokerage_paise=paise(brokerage),
        exchange_paise=paise(exchange),
        sebi_paise=paise(sebi),
        gst_paise=paise(gst),
        slippage_paise=paise(amount(slippage_inr)) if slippage_inr is not None else None,
        exercise_charge_paise=paise(exercise_charge),
        schedule_version='stt.2026-04-01' if modern else 'stt.2024-10-01',
        itm_expiry_stt_trap_warning=side in ('EXERCISE', 'ASSIGNMENT'),
        status='ESTIMATE',
        rounding='component-paise-half-up; contract-note aggregation unverified',
    )
    req_components = [result[k] for k in ('stt_paise', 'stamp_paise', 'brokerage_paise', 'exchange_paise', 'sebi_paise', 'gst_paise')]
    if side in ('EXERCISE', 'ASSIGNMENT'):
        # For exercise, exchange and sebi are not charged, only STT, brokerage, exercise charge, GST
        req_components = [result[k] for k in ('stt_paise', 'stamp_paise', 'brokerage_paise', 'gst_paise')]
    if all(x is not None for x in req_components):
        total = sum(req_components)
        if result['slippage_paise'] is not None:
            total += result['slippage_paise']
        if result['exercise_charge_paise'] is not None:
            total += result['exercise_charge_paise']
        result['total_paise'] = total
    else:
        result['total_paise'] = None
    return result


def declared_fee_estimate(transactions):
    """Aggregate explicit transaction scenarios; unknown charges never become zero."""
    if not transactions or len(transactions) > 200:
        raise ValueError('Bounded fee transactions required')
    results = []
    for row in transactions:
        brokerage_inr = row.get('brokerage_inr')
        charges = statutory_charges(
            row['product'],
            row['side'],
            row['turnover_inr'],
            row['trade_date'],
            brokerage_inr=brokerage_inr,
            exchange_rate=row.get('exchange_rate'),
            sebi_rate=row.get('sebi_rate'),
            slippage_inr=row.get('slippage_inr'),
            exercise_charge_inr=row.get('exercise_charge_inr'),
        )
        results.append(dict(
            transaction_id=row['transaction_id'],
            product=row['product'],
            side=row['side'],
            trade_date=row['trade_date'],
            turnover_inr=row['turnover_inr'],
            turnover_basis=row['turnover_basis'],
            cost_source=row['cost_source'],
            charges=charges,
        ))
    totals = [result['charges']['total_paise'] for result in results]
    return dict(
        transactions=results,
        total_paise=sum(totals) if all(value is not None for value in totals) else None,
        status='ESTIMATE',
        aggregation='sum_of_per_transaction_component_paise_estimates',
        stt_source='https://www.nseindia.in/static/products-services/equity-derivatives-securities-transaction-tax',
        limitations=['Broker/exchange/SEBI/slippage inputs are declared assumptions. Contract-note aggregation is unverified. A fee batch is not automatically bound to a strategy payoff.'],
    )


def reconcile_proposal_costs(proposal, *, entry_quotes, exit_quotes, entry_date, exit_date, fee_schedule=None):
    """Reconcile entry and exit costs for a StrategyProposal across effective dates."""
    fee_sched = fee_schedule or {}
    brokerage_inr = fee_sched.get('brokerage_per_order_inr')
    exchange_rate = fee_sched.get('exchange_rate')
    sebi_rate = fee_sched.get('sebi_rate')
    slippage_inr = fee_sched.get('slippage_inr')

    # Entry legs
    entry_charges_list = []
    for leg in proposal.legs:
        if leg.contract_id not in entry_quotes:
            raise ValueError(f"Missing quote for leg {leg.contract_id}")
        quote = entry_quotes[leg.contract_id]
        fill_price = Decimal(str(quote['ask' if leg.side == 'BUY' else 'bid']))
        turnover = fill_price * Decimal(str(leg.quantity))
        c = statutory_charges(
            'option',
            leg.side,
            turnover,
            entry_date,
            brokerage_inr=brokerage_inr,
            exchange_rate=exchange_rate,
            sebi_rate=sebi_rate,
            slippage_inr=slippage_inr,
        )
        entry_charges_list.append(c)

    # Exit legs (reversing positions)
    exit_charges_list = []
    for leg in proposal.legs:
        exit_side = 'SELL' if leg.side == 'BUY' else 'BUY'
        if leg.contract_id not in exit_quotes:
            raise ValueError(f"Missing quote for leg {leg.contract_id}")
        quote = exit_quotes[leg.contract_id]
        fill_price = Decimal(str(quote['bid' if exit_side == 'SELL' else 'ask']))
        turnover = fill_price * Decimal(str(leg.quantity))
        c = statutory_charges(
            'option',
            exit_side,
            turnover,
            exit_date,
            brokerage_inr=brokerage_inr,
            exchange_rate=exchange_rate,
            sebi_rate=sebi_rate,
            slippage_inr=slippage_inr,
        )
        exit_charges_list.append(c)

    def sum_key(lst, key):
        vals = [c[key] for c in lst]
        return sum(vals) if all(v is not None for v in vals) else None

    entry_total = sum_key(entry_charges_list, 'total_paise')
    exit_total = sum_key(exit_charges_list, 'total_paise')
    roundtrip = (entry_total + exit_total) if (entry_total is not None and exit_total is not None) else None

    return {
        'entry': {
            'schedule_version': entry_charges_list[0]['schedule_version'] if entry_charges_list else None,
            'stt_paise': sum_key(entry_charges_list, 'stt_paise'),
            'stamp_paise': sum_key(entry_charges_list, 'stamp_paise'),
            'brokerage_paise': sum_key(entry_charges_list, 'brokerage_paise'),
            'exchange_paise': sum_key(entry_charges_list, 'exchange_paise'),
            'sebi_paise': sum_key(entry_charges_list, 'sebi_paise'),
            'gst_paise': sum_key(entry_charges_list, 'gst_paise'),
            'total_paise': entry_total,
            'legs': entry_charges_list,
        },
        'exit': {
            'schedule_version': exit_charges_list[0]['schedule_version'] if exit_charges_list else None,
            'stt_paise': sum_key(exit_charges_list, 'stt_paise'),
            'stamp_paise': sum_key(exit_charges_list, 'stamp_paise'),
            'brokerage_paise': sum_key(exit_charges_list, 'brokerage_paise'),
            'exchange_paise': sum_key(exit_charges_list, 'exchange_paise'),
            'sebi_paise': sum_key(exit_charges_list, 'sebi_paise'),
            'gst_paise': sum_key(exit_charges_list, 'gst_paise'),
            'total_paise': exit_total,
            'legs': exit_charges_list,
        },
        'roundtrip_cost_paise': roundtrip,
        'status': 'RECONCILED' if roundtrip is not None else 'PARTIAL',
    }
