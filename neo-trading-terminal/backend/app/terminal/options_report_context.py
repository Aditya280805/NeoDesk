"""Owner-scoped saved evidence selection and deterministic whole-value summaries."""
import json
import sqlite3
from uuid import UUID
from fastapi import HTTPException

REPORT_KINDS = ('strategy', 'scan', 'alert', 'backtest')

def load_report(store, owner, kind, report_id):
    try:
        return _load_report(store,owner,kind,report_id)
    except sqlite3.Error:
        # Applies equally to initial selection, linked evidence and history.
        raise HTTPException(503,'Saved report storage unavailable. Retry shortly.') from None

def _load_report(store, owner, kind, report_id):
    if type(owner) is not int or owner <= 0 or kind not in REPORT_KINDS:
        raise ValueError('Invalid report selection')
    report_id = str(UUID(str(report_id)))
    queries = {
        'strategy': ("SELECT payload FROM options_platform_artifacts WHERE user_id=? AND id=? AND kind='analysis'",),
        'scan': ('SELECT payload FROM platform_scan_reports WHERE owner=? AND id=?',),
        'alert': ('SELECT payload FROM platform_alert WHERE owner=? AND id=?',),
        'backtest': ('SELECT payload FROM options_backtest_reports WHERE owner=? AND id=?',),
    }
    with store.connect() as db:
        row = db.execute(queries[kind][0], (owner, report_id)).fetchone()
    if row is None:
        raise HTTPException(404, 'Saved report unavailable for this account.')
    report = json.loads(row[0])
    linked = {}
    # Only owner-owned immutable evidence; no broker/session acquisition.
    with store.connect() as db:
        if kind == 'alert' and report.get('report_id'):
            risk = db.execute("SELECT payload FROM platform_records WHERE owner=? AND kind='risk' AND id=?",(owner,report['report_id'])).fetchone()
            if risk is None: raise HTTPException(503,'Saved alert evidence unavailable.')
            linked['risk_report'] = json.loads(risk[0])
    ids = set()
    def collect(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == 'evidence_id' and isinstance(item, str): ids.add(item)
                elif key == 'evidence_ids' and isinstance(item, list): ids.update(x for x in item if isinstance(x, str))
                collect(item)
        elif isinstance(value, list):
            for item in value: collect(item)
    collect(report)
    collect(linked)
    for key in ('dataset_hash','input_hash'):
        if isinstance(report.get(key),str): ids.add(report[key])
    with store.connect() as db:
        markets=[]
        for evidence_id in sorted(ids):
            row=db.execute("SELECT payload FROM options_platform_artifacts WHERE user_id=? AND kind='market' AND id=?",(owner,evidence_id)).fetchone()
            if row: markets.append(json.loads(row[0]))
        if markets: linked['market_evidence']=markets
    if linked: report=dict(report,linked_evidence=linked)
    return {'report_kind':kind, 'report_id':report_id, 'evidence_ids':sorted(ids), 'report':report,
        'observation_notice':'Historical saved observations only. State original observation times and age; unavailable times mean age is unknown. No fresh market claim.'}

def bounded_report(selected):
    """Preserve complete scalars, omit whole branches; never slice financial strings."""
    selected = json.loads(json.dumps(selected, allow_nan=False))
    if len(json.dumps(selected).encode()) <= 40000: return selected
    omissions = {}
    def summarize(value, path, depth=0):
        if isinstance(value, list):
            omissions[path] = len(value)
            return {'omitted_items':len(value)}
        if isinstance(value, dict):
            if depth >= 4:
                omissions[path] = len(value)
                return {'omitted_fields':len(value)}
            return {key:summarize(item, path+'.'+key, depth+1) for key,item in sorted(value.items())}
        if isinstance(value,str) and len(value.encode())>2000:
            omissions[path] = 1
            return {'omitted_scalar':True}
        return value
    result = {**selected, 'report':summarize(selected['report'],'report'),
        'full_report_reference':{'report_kind':selected['report_kind'],'report_id':selected['report_id']},
        'omitted_counts':omissions}
    if len(json.dumps(result).encode())>40000:
        result['report']={'omitted_fields':len(selected['report'])}
        result['omitted_counts']={'report':len(selected['report'])}
    if len(json.dumps(result).encode())>48000:
        raise HTTPException(503,'Selected report citation metadata exceeds the safe context limit.')
    return result
