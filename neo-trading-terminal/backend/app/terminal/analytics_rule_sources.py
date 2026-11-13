"""Map published stock bans only through exact documented master identities."""

def map_published_bans(positions,publication,lookup):
    findings = []
    for position in positions:
        identifier = position['contract_id']
        finding = dict(contract_id=identifier,status='unavailable',ban_active=None,
                       reason='verified_nse_derivative_master_required')
        try:
            item = lookup(identifier)
        except (KeyError,ValueError):
            item = None
        if isinstance(item,dict):
            raw,source = item.get('identity_source_fields',{}),item.get('source_metadata',{})
            valid = (source.get('source')=='kotak-scrip-master' and
                item.get('id')==identifier=='nse_fo|'+str(raw.get('pSymbol')) and
                item.get('exchange')==raw.get('pExchSeg')=='nse_fo' and
                str(item.get('token'))==str(raw.get('pSymbol')) and
                bool(raw.get('pSymbolName')) and
                item.get('underlying')==raw.get('pSymbolName')==position.get('underlying'))
            if valid:
                kind = source.get('pInstType')
                if kind in ('OPTSTK','FUTSTK'):
                    finding.update(status='available',ban_active=raw['pSymbolName'] in publication['symbols'],
                        reason='official_publication_exact_master_underlying')
                elif kind in ('OPTIDX','FUTIDX'):
                    finding.update(status='not_applicable',reason='stock_ban_not_applicable_to_index')
        findings.append(finding)
    return findings
