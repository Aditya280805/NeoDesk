"""Advisory checks. Rule data must be supplied by verified server evidence."""


def compliance_checks(positions, rules):
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
