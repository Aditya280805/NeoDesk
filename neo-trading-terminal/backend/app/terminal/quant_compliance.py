"""Advisory checks. Rule data must be supplied by verified server evidence."""


def compliance_checks(positions, rules):
    if 'declared_records' in rules:
        return declared_compliance_checks(positions,rules['declared_records'])
    findings = []
    def finding(code,outcome,reason,contract=None):
        findings.append(dict(code=code,outcome=outcome,reason=reason,contract_id=contract))
    for row in positions:
        contract = row['contract_id']
        qty,lot = row.get('quantity'),row.get('lot_size')
        if not isinstance(qty,int) or isinstance(qty,bool) or not isinstance(lot,int) or isinstance(lot,bool) or lot <= 0:
            finding('lot_multiple','cannot_assess','missing_verified_contract_quantity',contract)
        else:
            finding('lot_multiple','breach' if qty % lot else 'pass','contract_lot_check',contract)
        banned = rules.get('ban_status',{}).get(contract)
        if banned is None:
            finding('mwpl','cannot_assess','missing_published_ban_status',contract)
        elif banned:
            finding('mwpl','breach' if row.get('increases_exposure') is True else 'cannot_assess', 'BAN_ACTIVE_REDUCE_ONLY',contract)
        else:
            finding('mwpl','pass','published_not_banned',contract)
    for code in ('expiry_elm','calendar_spread_margin','delta_position_limit'):
        finding(code,'cannot_assess','missing_applicable_verified_rule_or_margin_inputs')
    verdict = 'BREACH_HALT_REQUIRED' if any(x['outcome']=='breach' for x in findings) else 'CANNOT_ASSESS'
    return dict(findings=findings,risk_verdict=verdict,read_only=True)


def declared_compliance_checks(positions,records):
    """Conservative scenario checks, never certification of exchange compliance.

    A per-contract declaration cannot prove underlying-wide/account aggregation or
    intraday/base-day monitoring. All operational verdicts remain unavailable.
    """
    by_id = {record['contract_id']:record for record in records}
    findings = []
    for position in positions:
        identifier = position['contract_id']
        rule = by_id.get(identifier,{})
        qty,lot = position['quantity'],rule.get('lot_size')
        if rule.get('instrument_scope') not in ('stock_derivative','index_derivative'):
            lot = None
        findings.append(dict(code='lot_multiple',contract_id=identifier,
            outcome='cannot_assess' if lot is None else 'breach' if qty%lot else 'pass',
            reason='declared_lot_scenario' if lot is not None else 'missing_declared_lot'))
        banned = rule.get('ban_active')
        base,current = rule.get('base_futeq'),rule.get('current_futeq')
        outcome,reason = 'cannot_assess','missing_effective_ban_or_futeq_inputs'
        if rule.get('instrument_scope')!='stock_derivative':
            reason='stock_mwpl_rule_not_applicable_or_scope_unverified'
        elif banned is False:
            outcome,reason = 'pass','declared_not_banned_scenario'
        elif banned is True and base is not None and current is not None:
            if base*current<0:
                outcome,reason = 'breach','ban_delta_sign_reversal'
            elif abs(current)>abs(base):
                outcome,reason = 'breach','ban_declared_exposure_increase'
            else:
                reason = 'reduction_declared_but_account_and_intraday_coverage_unverified'
        findings.append(dict(code='mwpl',contract_id=identifier,outcome=outcome,reason=reason))
    for code in ('expiry_elm','calendar_spread_margin','delta_position_limit','account_aggregation','intraday_peak_exposure'):
        findings.append(dict(code=code,contract_id=None,outcome='cannot_assess',reason='verified_applicable_rule_and_complete_account_inputs_required'))
    return dict(findings=findings,risk_verdict='CANNOT_ASSESS',scenario_verdict='DECLARED_BREACH' if any(item['outcome']=='breach' for item in findings) else 'INCOMPLETE',
        rule_coverage=[{key:record[key] for key in ('contract_id','source','revision','instrument_scope','valid_from','valid_until')} for record in records],
        read_only=True,limitations=['User-declared effective-date scenarios only. Per-contract FutEq does not establish underlying-wide or complete-account compliance. No automatic kill switch or order action.'])
