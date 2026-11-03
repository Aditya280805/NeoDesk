"""Pure conservative portfolio checks. No adapter semantics are inferred here."""
from datetime import datetime, timedelta, timezone
from decimal import Context, Decimal, DecimalException, DivisionByZero, InvalidOperation, Overflow, ROUND_HALF_EVEN, localcontext
from zoneinfo import ZoneInfo
from uuid import uuid4 as new_report_id
from pydantic import ValidationError
from .portfolio_contracts import MarginRiskInput, PnlRiskInput
from .portfolio_risk_contracts import RiskPolicy, RiskFinding, RiskReport, RiskCoverage, RiskObservationTimes
MARGIN_BASIS = 'broker_account_total_margin'
INDIA = ZoneInfo('Asia/Kolkata')

class Unavailable(Exception):
    pass

def number(value):
    if value is None:
        raise Unavailable('missing_value')
    if isinstance(value, bool):
        raise Unavailable('calculation_unavailable')
    try:
        result = Decimal(str(value))
    except (ValueError, DecimalException):
        raise Unavailable('calculation_unavailable')
    if not result.is_finite() or len(result.as_tuple().digits) > 24 or (result and (result.adjusted() > 23 or result.adjusted() < -8)) or (result.as_tuple().exponent < -8):
        raise Unavailable('calculation_unavailable')
    return result

def wire(value):
    value = number(value)
    text = format(value, 'f')
    if '.' in text:
        text = text.rstrip('0').rstrip('.')
    return '0' if value == 0 else text

def aware(value):
    return isinstance(value, datetime) and value.tzinfo is not None and (value.utcoffset() is not None)

def fresh(start, finish, now, age):
    if not aware(start) or not aware(finish) or (not start <= finish <= now):
        raise Unavailable('invalid_observation_time')
    if age is None:
        raise Unavailable('freshness_limit_not_configured')
    if now - start > timedelta(seconds=age):
        raise Unavailable('stale_observation')

def evaluate_portfolio_risk(snapshot, policy, as_of):
    """Evaluate exact comparisons; display ratios are rounded independently."""
    if not aware(as_of) or as_of.utcoffset() != timedelta(0):
        raise ValueError('as_of must be timezone-aware UTC')
    policy = RiskPolicy.model_validate(policy.model_dump(mode='python'))
    findings = []
    times = {}
    for name, section in snapshot.sections.items():
        times[name] = RiskObservationTimes(retrieval_started_at=section.retrieval_started_at, retrieval_finished_at=section.retrieval_finished_at, source_timestamp=section.provider_timestamp)
    for code in ('concentration', 'expiry', 'margin', 'loss'):
        enabled = getattr(policy, code + '_enabled')
        limit = getattr(policy, {'concentration': 'concentration_max_percent', 'expiry': 'expiry_window_days', 'margin': 'margin_max_percent', 'loss': 'loss_max_amount'}[code])
        data = dict(code=code, enabled=enabled, outcome='cannot_assess', limit=str(limit) if limit is not None else None, unit='days' if code == 'expiry' else 'INR' if code == 'loss' else 'percent')
        try:
            if not enabled:
                raise Unavailable('check_disabled')
            if limit is None:
                raise Unavailable('limit_not_configured')
            section = snapshot.sections.get({'concentration': 'holdings', 'expiry': 'positions', 'margin': 'funds', 'loss': 'funds'}[code])
            if section is None:
                raise Unavailable('section_unavailable')
            fresh(snapshot.retrieval_started_at, snapshot.retrieval_finished_at, as_of, policy.max_observation_age_seconds)
            fresh(section.retrieval_started_at, section.retrieval_finished_at, as_of, policy.max_observation_age_seconds)
            if section.provider_timestamp is not None:
                if not aware(section.provider_timestamp) or section.provider_timestamp > as_of:
                    raise Unavailable('invalid_observation_time')
            # Isolate precision and traps from the caller; threshold comparisons
            # use exact cross-products before display rounding.
            with localcontext(Context(prec=80, rounding=ROUND_HALF_EVEN, Emin=-100, Emax=100, capitals=1, clamp=0, flags=[], traps=[InvalidOperation, DivisionByZero, Overflow])):
                if code == 'concentration':
                    _concentration(section, limit, data)
                elif code == 'expiry':
                    _expiry(section, limit, as_of, data)
                else:
                    _account_input(snapshot, section, code, policy, limit, as_of, data, times)
        except Unavailable as exc:
            data.update(outcome='cannot_assess', reason_codes=[str(exc)])
        except (DecimalException, OverflowError, ValueError, TypeError, AttributeError):
            data.update(outcome='cannot_assess', reason_codes=['calculation_unavailable'])
        if data['outcome'] == 'cannot_assess':
            for name in ('measured', 'numerator', 'denominator'):
                data.pop(name, None)
        findings.append(RiskFinding(**data))
    counts = {k: sum((f.enabled and f.outcome == v for f in findings)) for k, v in [('passed', 'pass'), ('breached', 'breach'), ('cannot_assess', 'cannot_assess')]}
    counts['disabled'] = sum((not f.enabled for f in findings))
    summary = 'breach' if counts['breached'] else 'cannot_assess' if counts['cannot_assess'] or counts['disabled'] == 4 else 'pass'
    return RiskReport(report_id=new_report_id(), evidence_id=snapshot.evidence_id, policy_revision=policy.revision, evaluated_at=as_of, observation_times=times, summary=summary, coverage=RiskCoverage(**counts), findings=findings, limitations=sorted({r for f in findings for r in f.reason_codes if f.outcome == 'cannot_assess'}))

def ratio(data, numerator, denominator, limit):
    outcome = 'breach' if numerator * 100 > limit * denominator else 'pass'
    measured = (numerator * 100 / denominator).quantize(Decimal('0.00000001'))
    data.update(numerator=wire(numerator), denominator=wire(denominator), measured=wire(measured), outcome=outcome, reason_codes=[])


def _concentration(section, limit, data):
    if section.state != 'available' or section.issues:
        raise Unavailable('incomplete_coverage')
    groups = {}
    keys = {}
    ids = set()
    for r in section.rows:
        q = number(r.quantity)
        v = number(r.market_value)
        if q == 0 and v == 0:
            continue
        if q <= 0 or v < 0:
            raise Unavailable('unsupported_holdings_value')
        if r.currency != 'INR':
            raise Unavailable('unsupported_currency')
        if r.identity_verified is not True or not r.underlying_key or (not r.underlying_identity_basis) or r.issues:
            raise Unavailable('unverified_underlying')
        if r.row_id in ids:
            raise Unavailable('ambiguous_inventory')
        ids.add(r.row_id)
        prior = keys.setdefault(r.underlying_key, [])
        prior.append(r)
        if r.inventory_coverage == 'ambiguous' or (len(prior) > 1 and any((x.inventory_coverage != 'disjoint' or not x.inventory_coverage_basis for x in prior))):
            raise Unavailable('ambiguous_inventory')
        groups[r.underlying_key] = groups.get(r.underlying_key, Decimal(0)) + v
    total = sum(groups.values(), Decimal(0))
    largest = max(groups.values(), default=Decimal(0))
    if total <= 0:
        raise Unavailable('invalid_denominator')
    key = max(groups, key=groups.get)
    data['affected_row_ids'] = [r.row_id for r in keys[key]]
    ratio(data, largest, total, number(limit))


def _expiry(section, limit, as_of, data):
    reasons = []
    affected = []
    unknown = section.state != 'available' or bool(section.issues)
    for r in section.rows:
        try:
            q = number(r.quantity)
        except Unavailable as exc:
            if str(exc) == 'calculation_unavailable':
                raise
            unknown = True
            continue
        if q == 0:
            continue
        if r.identity_verified is not True:
            unknown = True
            continue
        kind = (r.contract_type or '').upper()
        if kind in ('EQUITY', 'EQ', 'STOCK', 'INDEX'):
            continue
        if kind not in ('FUT', 'FUTURE', 'FUTURES', 'OPT', 'OPTION', 'OPTIONS', 'CE', 'PE') or r.expiry is None:
            unknown = True
            continue
        days = (r.expiry - as_of.astimezone(INDIA).date()).days
        if days <= limit:
            reasons.append('expired_open' if days < 0 else 'expiry_within_window')
            affected.append(r.row_id)
    if affected:
        data.update(outcome='breach', affected_row_ids=affected, reason_codes=sorted(set(reasons)))
    elif unknown:
        raise Unavailable('incomplete_coverage')
    else:
        data.update(outcome='pass', reason_codes=[])
    if unknown and affected:
        data['reason_codes'].append('incomplete_coverage')


def _account_input(snapshot, section, code, policy, limit, as_of, data, times):
    if section.state != 'available':
        raise Unavailable('incomplete_coverage')
    record = getattr(snapshot.risk_inputs, 'margin' if code == 'margin' else 'pnl', None)
    if record is None:
        raise Unavailable('missing_risk_input')
    try:
        record = (MarginRiskInput if code == 'margin' else PnlRiskInput).model_validate(record.model_dump(mode='python', warnings=False))
    except (ValidationError, ValueError):
        raise Unavailable('calculation_unavailable')
    times[code] = RiskObservationTimes(source_timestamp=record.source_timestamp)
    fresh(record.source_timestamp, record.source_timestamp, as_of, policy.max_observation_age_seconds)
    if record.currency != 'INR':
        raise Unavailable('unsupported_currency')
    names = ('used_margin', 'total_margin') if code == 'margin' else ('account_net_pnl',)
    if any((n not in record.provenance or not record.provenance[n].input_paths or (not record.provenance[n].basis) for n in names)):
        raise Unavailable('unsupported_basis')
    if code == 'margin':
        if record.basis != MARGIN_BASIS or record.period != 'point_in_time' or record.period_start is not None or (record.period_end is not None):
            raise Unavailable('unsupported_basis')
        used = number(record.used_margin)
        total = number(record.total_margin)
        if used < 0:
            raise Unavailable('unsupported_margin_value')
        if total <= 0:
            raise Unavailable('invalid_denominator')
        ratio(data, used, total, number(limit))
    else:
        if record.basis != policy.loss_basis or record.period != policy.loss_period:
            raise Unavailable('unsupported_basis')
        start, end = (record.period_start, record.period_end)
        day = as_of.astimezone(INDIA).date()
        expected = datetime.combine(day, datetime.min.time(), INDIA)
        if not aware(start) or not aware(end) or start != expected or (end != expected + timedelta(days=1)) or (not start <= record.source_timestamp <= as_of < end):
            raise Unavailable('unsupported_period')
        loss = max(Decimal(0), -number(record.account_net_pnl))
        data.update(measured=wire(loss), outcome='breach' if loss > number(limit) else 'pass', reason_codes=[])
