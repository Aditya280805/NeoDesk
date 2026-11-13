"""Advisory checks. Rule data must be supplied by verified server evidence."""
from datetime import date, datetime
from zoneinfo import ZoneInfo
from decimal import Decimal, ROUND_HALF_UP


def compliance_checks(positions, rules):
    if 'declared_records' in rules:
        result = declared_compliance_checks(positions, rules['declared_records'])
        if rules.get('as_of') is not None:
            result['expiry_rule_applicability'] = expiry_rule_applicability(positions, rules['declared_records'], rules['as_of'])
        return result
    findings = []
    def finding(code, outcome, reason, contract=None):
        findings.append(dict(code=code, outcome=outcome, reason=reason, contract_id=contract))
    for row in positions:
        contract = row['contract_id']
        qty, lot = row.get('quantity'), row.get('lot_size')
        if not isinstance(qty, int) or isinstance(qty, bool) or not isinstance(lot, int) or isinstance(lot, bool) or lot <= 0:
            finding('lot_multiple', 'cannot_assess', 'missing_verified_contract_quantity', contract)
        else:
            finding('lot_multiple', 'breach' if qty % lot else 'pass', 'contract_lot_check', contract)
        banned = rules.get('ban_status', {}).get(contract)
        if banned is None:
            finding('mwpl', 'cannot_assess', 'missing_published_ban_status', contract)
        elif banned:
            finding('mwpl', 'breach' if row.get('increases_exposure') is True else 'cannot_assess', 'BAN_ACTIVE_REDUCE_ONLY', contract)
        else:
            finding('mwpl', 'pass', 'published_not_banned', contract)
    for code in ('expiry_elm', 'calendar_spread_margin', 'delta_position_limit'):
        finding(code, 'cannot_assess', 'missing_applicable_verified_rule_or_margin_inputs')
    verdict = 'BREACH_HALT_REQUIRED' if any(x['outcome'] == 'breach' for x in findings) else 'CANNOT_ASSESS'
    return dict(findings=findings, risk_verdict=verdict, read_only=True)


def aggregate_underlying_compliance(positions, records):
    """Aggregate per-underlying exposure across multiple contracts for stock MWPL ban and limits."""
    pos_by_id = {p['contract_id']: p for p in positions}
    rec_by_id = {r['contract_id']: r for r in records}

    underlyings = {}
    for cid, r in rec_by_id.items():
        u = r.get('underlying') or (pos_by_id.get(cid, {}).get('underlying')) or cid
        underlyings.setdefault(u, []).append((pos_by_id.get(cid, {}), r))

    underlying_summaries = {}
    findings = []

    for u, pairs in underlyings.items():
        scope = pairs[0][1].get('instrument_scope')
        if scope != 'stock_derivative':
            continue
        ban_active = any(r.get('ban_active') is True for _, r in pairs)
        has_base = all(r.get('base_futeq') is not None and r.get('futeq_basis','per_contract')=='per_contract' for _, r in pairs)
        has_curr = all(r.get('current_futeq') is not None and r.get('futeq_basis','per_contract')=='per_contract' for _, r in pairs)

        base_futeq = sum(r.get('base_futeq') or 0 for _, r in pairs) if has_base else None
        current_futeq = sum(r.get('current_futeq') or 0 for _, r in pairs) if has_curr else None

        exp_increased = False
        sign_reversed = False
        if base_futeq is not None and current_futeq is not None:
            if base_futeq * current_futeq < 0:
                sign_reversed = True
            elif abs(current_futeq) > abs(base_futeq):
                exp_increased = True

        underlying_summaries[u] = {
            'underlying': u,
            'instrument_scope': scope,
            'ban_active': ban_active,
            'aggregate_base_futeq': base_futeq,
            'aggregate_current_futeq': current_futeq,
            'aggregate_exposure_increased': exp_increased,
            'aggregate_sign_reversed': sign_reversed,
        }

        if ban_active:
            if sign_reversed:
                findings.append(dict(
                    code='aggregate_underlying_mwpl',
                    underlying=u,
                    outcome='breach',
                    reason='ban_delta_sign_reversal',
                    measured=current_futeq,
                    base=base_futeq,
                ))
            elif exp_increased:
                findings.append(dict(
                    code='aggregate_underlying_mwpl',
                    underlying=u,
                    outcome='breach',
                    reason='ban_declared_exposure_increase',
                    measured=current_futeq,
                    base=base_futeq,
                ))
            else:
                findings.append(dict(
                    code='aggregate_underlying_mwpl',
                    underlying=u,
                    outcome='cannot_assess',
                    reason='reduction_declared_but_account_and_intraday_coverage_unverified',
                    measured=current_futeq,
                    base=base_futeq,
                ))

    return {
        'underlying_summaries': underlying_summaries,
        'findings': findings,
    }


def declared_compliance_checks(positions, records):
    """Conservative scenario checks, never certification of exchange compliance.

    A per-contract declaration cannot prove underlying-wide/account aggregation or
    intraday/base-day monitoring. All operational verdicts remain unavailable.
    """
    by_id = {record['contract_id']: record for record in records}
    findings = []
    for position in positions:
        identifier = position['contract_id']
        rule = by_id.get(identifier, {})
        qty, lot = position['quantity'], rule.get('lot_size')
        if rule.get('instrument_scope') not in ('stock_derivative', 'index_derivative'):
            lot = None
        findings.append(dict(
            code='lot_multiple',
            contract_id=identifier,
            outcome='cannot_assess' if lot is None else 'breach' if qty % lot else 'pass',
            reason='declared_lot_scenario' if lot is not None else 'missing_declared_lot',
        ))
        banned = rule.get('ban_active')
        base, current = rule.get('base_futeq'), rule.get('current_futeq')
        outcome, reason = 'cannot_assess', 'missing_effective_ban_or_futeq_inputs'
        if rule.get('instrument_scope') != 'stock_derivative':
            reason = 'stock_mwpl_rule_not_applicable_or_scope_unverified'
        elif banned is False:
            outcome, reason = 'pass', 'declared_not_banned_scenario'
        elif banned is True and base is not None and current is not None:
            if base * current < 0:
                outcome, reason = 'breach', 'ban_delta_sign_reversal'
            elif abs(current) > abs(base):
                outcome, reason = 'breach', 'ban_declared_exposure_increase'
            else:
                reason = 'reduction_declared_but_account_and_intraday_coverage_unverified'
        findings.append(dict(code='mwpl', contract_id=identifier, outcome=outcome, reason=reason))
        limit = rule.get('underlying_futeq_limit')
        if limit is not None and rule.get('futeq_basis') == 'declared_underlying_aggregate':
            breach = current is not None and abs(current) > limit
            findings.append(dict(
                code='declared_underlying_futeq_limit',
                contract_id=identifier,
                outcome='breach' if breach else 'cannot_assess',
                reason='declared_aggregate_limit_exceeded' if breach else 'aggregate_measure_or_complete_account_limit_coverage_unverified',
                measured=current,
                limit=limit,
                basis='user_declared_underlying_aggregate',
            ))

    # Add aggregate underlying findings
    agg_result = aggregate_underlying_compliance(positions, records)
    findings.extend(agg_result['findings'])

    for code in ('expiry_elm', 'calendar_spread_margin', 'delta_position_limit', 'account_aggregation', 'intraday_peak_exposure'):
        findings.append(dict(code=code, contract_id=None, outcome='cannot_assess', reason='verified_applicable_rule_and_complete_account_inputs_required'))
    return dict(
        findings=findings,
        risk_verdict='CANNOT_ASSESS',
        scenario_verdict='DECLARED_BREACH' if any(item['outcome'] == 'breach' for item in findings) else 'INCOMPLETE',
        rule_coverage=[{key: record.get(key) for key in ('contract_id', 'source', 'revision', 'instrument_scope', 'valid_from', 'valid_until')} for record in records],
        underlying_summaries=agg_result['underlying_summaries'],
        read_only=True,
        limitations=['User-declared effective-date scenarios only. Per-contract FutEq does not establish underlying-wide or complete-account compliance. No automatic kill switch or order action.'],
    )


def expiry_rule_applicability(positions, records, as_of):
    """Published rule applicability under declared classification, not total margin."""
    india = ZoneInfo('Asia/Kolkata')
    day = datetime.fromisoformat(as_of).astimezone(india).date()
    scopes = {record['contract_id']: record['instrument_scope'] for record in records}
    result = []
    for position in positions:
        scope = scopes.get(position['contract_id'])
        expiry = datetime.fromisoformat(position['expiry_at']).astimezone(india).date() if position.get('expiry_at') else None
        expiring = expiry == day if expiry is not None else None
        elm = .02 if scope == 'index_derivative' and position.get('kind') == 'option' and position.get('quantity', 0) < 0 and expiring and day >= date(2024, 11, 20) else None
        increment = None
        if elm is not None and position.get('spot') is not None:
            value = Decimal(str(position['spot'])) * abs(position['quantity']) * Decimal('2')
            if value.is_finite() and 0 < value <= 9007199254740991:
                increment = int(value.quantize(Decimal('1'), rounding=ROUND_HALF_UP))
        cutoff = date(2025, 2, 10) if scope == 'index_derivative' else date(2026, 5, 4) if scope == 'stock_derivative' else None
        excluded = bool(cutoff and expiring and day >= cutoff)
        result.append(dict(
            contract_id=position['contract_id'],
            valuation_date=day.isoformat(),
            expiry_date=expiry.isoformat() if expiry else None,
            classification_basis='user_declared_unverified',
            additional_expiry_elm_rate=elm,
            total_margin_paise=None,
            modeled_additional_expiry_elm_paise=increment,
            modeled_elm_basis='declared_underlying_spot_times_short_economic_units_times_2pct; not_broker_margin',
            calendar_spread_benefit_for_expiring_contract=False if excluded else None,
            elm_rule='NCL/CMPT/64639 effective 2024-11-20',
            calendar_rule='NCL/CMPT/66047 effective 2025-02-10' if scope == 'index_derivative' else 'NCL/CMPT/72906 effective 2026-05-04' if scope == 'stock_derivative' else None,
            limitation='Declared scenario increment only; baseline/deep-OTM ELM, SPAN, eligible non-expiring pairs and broker margin are not computed. Missing or unsafe paise amounts stay unavailable.',
        ))
    return result
