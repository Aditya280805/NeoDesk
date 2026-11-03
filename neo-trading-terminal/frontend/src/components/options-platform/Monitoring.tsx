import { useCallback, useEffect, useRef, useState } from 'react'
import { integer, moneyText, object, rows, text } from '@/lib/optionsPlatform'
import { ActionForm, Evidence, Fields, InputFields } from './Forms'
import { useWorkspace } from './Workspace'

const policyKeys = ['capital_cap_inr', 'underlying_exposure_maxpercent', 'strategy_maxloss_inr', 'drawdown_maxpercent', 'observation_max_age_seconds']
const pageSize = 20
function ReferencePage({ label, ids, offset, total, onPage }: {
  label: string; ids: string[]; offset: number; total: number; onPage: (offset: number) => void
}) {
  return <><p>{label} selected ({ids.length}): {ids.length ? ids.join(', ') : 'None'}</p>
    {total > pageSize && <nav aria-label={`${label} pages`}>
      <button type="button" disabled={!offset} onClick={() => onPage(offset - pageSize)}>Previous {label}</button>
      <span> {offset + 1}–{Math.min(offset + pageSize, total)} of {total} </span>
      <button type="button" disabled={offset + pageSize >= total} onClick={() => onPage(offset + pageSize)}>Next {label}</button>
    </nav>}</>
}
const ledgerExample = { version: 'user-lot-ledger.v1', source: 'user_declared', currency: 'INR', allocation_method: 'FIFO', coverage_start: '2026-11-01T00:00:00+05:30', coverage_end: '2026-11-02T10:00:00+05:30', opening_inventory: [{ contract_id: 'nse_cm|123', quantity: 0 }, { contract_id: 'nse_fo|456', quantity: 0 }], trades: [{ sequence: 0, fill_id: 'declared-stock-buy', contract_id: 'nse_cm|123', side: 'BUY', quantity: 10, price: '100', costs_inr: '1', executed_at: '2026-11-01T10:00:00+05:30' }, { sequence: 1, fill_id: 'declared-call-sell', contract_id: 'nse_fo|456', side: 'SELL', quantity: 10, price: '5', costs_inr: '1', executed_at: '2026-11-01T10:00:00+05:30' }], complete: true }
export default function Monitoring({ visible }: { visible: boolean }) {
  const { request, cancel, busy, selectReport } = useWorkspace()
  const [policy, setPolicy] = useState<Fields>({}), [revision, setRevision] = useState<number | null>(null), [monitor, setMonitor] = useState<unknown>(), [alerts, setAlerts] = useState<unknown>(), [risk, setRisk] = useState<unknown>()
  const [offset, setOffset] = useState(0), [baselines, setBaselines] = useState<unknown>(), [portfolios, setPortfolios] = useState<unknown>(), [ledgers, setLedgers] = useState<unknown>(), [association, setAssociation] = useState<unknown>()
  const [v, setV] = useState<Fields>({ baseline: '', portfolio: '', ledger: '', costs: '', interval: '60' }), [rowIds, setRowIds] = useState<string[]>([]), [fillIds, setFillIds] = useState<string[]>([]), [confirmed, setConfirmed] = useState(false)
  const [ledger, setLedger] = useState(JSON.stringify(ledgerExample, null, 2)), [complete, setComplete] = useState(false), [importResult, setImportResult] = useState<unknown>(), [error, setError] = useState('')
  const [equity, setEquity] = useState<Fields[]>([{ observed_at: '', equity_inr: '', external_flow_inr: '0' }])
  const [rowOffset, setRowOffset] = useState(0), [fillOffset, setFillOffset] = useState(0)
  const alertContext = useRef({ offset: 0, operation: 0 }), associationOperation = useRef(0)
  const refreshAlerts = useCallback(async () => {
    const context = alertContext.current, operation = ++context.operation
    const data = await request(`/alerts?limit=${pageSize}&offset=${context.offset}`, 'GET', undefined, 'monitor-alerts')
    if (alertContext.current === context && operation === context.operation && data !== undefined) setAlerts(data)
  }, [request])
  const refresh = useCallback(() => Promise.all([
    request('/monitoring').then(data => { if (data !== undefined) setMonitor(data) }),
    refreshAlerts(),
    request('/risk-reports?limit=20&offset=0').then(data => { if (data !== undefined) setRisk(data) }),
  ]), [request, refreshAlerts])
  function changeAlertPage(next: number) {
    alertContext.current = { offset: next, operation: 0 }
    cancel('monitor-alerts')
    setOffset(next)
    setAlerts(undefined)
    void refreshAlerts()
  }
  function changeAssociation(next: Fields, acquired = false) {
    if (next.baseline !== v.baseline || next.portfolio !== v.portfolio || next.ledger !== v.ledger) {
      associationOperation.current++
      cancel('monitor-association')
      cancel('monitor-portfolio-acquisition')
      setAssociation(undefined)
      setRowIds([]); setFillIds([]); setConfirmed(false)
      setRowOffset(0); setFillOffset(0)
    }
    setV(previous => acquired ? { ...previous, portfolio: next.portfolio } : next)
  }
  async function loadAssociation(method: 'GET' | 'POST', body?: unknown) {
    const operation = ++associationOperation.current
    const path = `/baselines/${v.baseline}/associations`
    const data = await request(method === 'GET' ? `${path}?limit=20&offset=0` : path,
      method, body, 'monitor-association')
    if (operation === associationOperation.current && data !== undefined) setAssociation(data)
  }
  async function acquirePortfolio() {
    const operation = associationOperation.current
    const data = await request('/association-evidence', 'POST', undefined, 'monitor-portfolio-acquisition')
    if (data === undefined || operation !== associationOperation.current) return
    setPortfolios((previous: unknown) => [data, ...rows(previous)])
    const portfolio = String(object(object(data).snapshot).evidence_id)
    changeAssociation({ ...v, portfolio }, true)
  }
  const reloadPolicy = useCallback(async () => { const data = await request('/risk-policy'); if (data !== undefined) { const p = object(data); setRevision(Number(p.revision)); setPolicy(Object.fromEntries(policyKeys.map(k => [k, p[k] == null ? '' : String(p[k])]))) } }, [request])
  useEffect(() => { if (!visible) return; const initial = setTimeout(() => { if (document.visibilityState === 'visible') void refresh() }, 0); const timer = setInterval(() => { if (document.visibilityState === 'visible') void refresh() }, 60000); const resume = () => { if (document.visibilityState === 'visible') void refresh() }; document.addEventListener('visibilitychange', resume); return () => { clearTimeout(initial); clearInterval(timer); document.removeEventListener('visibilitychange', resume) } }, [visible, refresh])
  const safe = async (fn: () => Promise<void>) => { try { setError(''); await fn() } catch (e) { setError((e as Error).message) } }
  const loadAssociations = async () => { for (const [path, setter] of [['baselines', setBaselines], ['association-evidence', setPortfolios], ['lot-ledger-imports', setLedgers]] as const) { const data = await request(`/${path}?limit=100&offset=0`); if (data !== undefined) setter(data) } }
  const selected = rows(portfolios).find(r => String(object(r.snapshot).evidence_id) === v.portfolio), snapshot = object(selected?.snapshot)
  const ledgerSelected = rows(ledgers).find(r => String(r.id) === v.ledger)
  const serverRows = Object.values(object(snapshot.sections)).flatMap(s => rows(object(s).rows)), fills = v.ledger ? rows(ledgerSelected?.trades) : rows(object(selected?.fills).fills)
  const toggle = (values: string[], id: string) => values.includes(id) ? values.filter(x => x !== id) : [...values, id]
  return <>{error && <p role="alert">{error}</p>}<section className="op-panel"><h2>Independent monitoring</h2><p>Explicit opt-in, at least 60 seconds. Server jobs continue when this page closes. Missing broker sessions suspend collection. This panel refreshes visible status only; no model is called.</p><InputFields values={v} onChange={setV} specs={[{ key: 'interval', label: 'Monitoring interval seconds' }]} /><button disabled={busy} onClick={() => void safe(async () => { const data = await request('/monitoring', 'PUT', { enabled: true, interval_seconds: integer(v.interval, 60, 86400) }); if (data !== undefined) setMonitor(data) })}>Enable monitoring</button><button disabled={busy} onClick={async () => { const data = await request('/monitoring', 'PUT', { enabled: false, interval_seconds: 60 }); if (data !== undefined) setMonitor(data) }}>Disable monitoring</button><button onClick={() => void refresh()}>Refresh monitoring and alerts</button><Evidence value={monitor ?? 'Not loaded'} /></section>
    <ActionForm title="Risk policy · unset values cannot be assessed" action="Save risk policy revision" disabled={busy || revision === null} onSubmit={() => void safe(async () => { const payload = Object.fromEntries(policyKeys.map(k => [k, k === 'observation_max_age_seconds' ? policy[k] ? integer(policy[k], 1, 86400) : null : moneyText(policy[k] ?? '', true)])); const data = await request('/risk-policy', 'PUT', { revision, ...payload }); if (data !== undefined) setRevision(Number(object(data).revision)) })}><button type="button" onClick={() => void reloadPolicy()}>Load current policy (replaces draft)</button><p>Loaded revision: {revision ?? 'not loaded'}. On conflict retain this draft, then explicitly reload before retrying.</p><InputFields values={policy} onChange={setPolicy} specs={policyKeys.map(key => ({ key, label: key.replaceAll('_', ' '), optional: true }))} /></ActionForm>
    <section className="op-panel"><h2>Explicit baseline association</h2><p>Select exact owner evidence rows and opening fills. No automatic matching. Day fills support mark-versus-selected-fill comparison only, not actual P&amp;L. User-declared complete FIFO history is separately sourced.</p><button onClick={() => void loadAssociations()}>Load saved baselines, owner evidence and ledgers</button><button disabled={busy} onClick={() => acquirePortfolio()}>Acquire current server portfolio evidence</button><InputFields values={v} onChange={changeAssociation} specs={[
      { key: 'baseline', label: 'Saved baseline', options: rows(baselines).map(r => ({ value: String(r.baseline_id), label: `${r.name} · ${r.baseline_id}` })) }, { key: 'portfolio', label: 'Server portfolio evidence', options: rows(portfolios).map(r => ({ value: String(object(r.snapshot).evidence_id), label: `${object(r.snapshot).evidence_id} · ${text(object(r.snapshot).source_observed_at)}` })) }, { key: 'ledger', label: 'User-declared FIFO ledger', optional: true, options: rows(ledgers).map(r => ({ value: String(r.id), label: `${r.id} · coverage end ${text(r.coverage_end)}` })) }, { key: 'costs', label: 'User-declared association costs INR', optional: true }
    ]} /><fieldset><legend>Exact inventory rows</legend>{serverRows.slice(rowOffset, rowOffset + pageSize).map((r, i) => <label key={i}><input type="checkbox" checked={rowIds.includes(String(r.row_id))} disabled={rowIds.length >= 20 && !rowIds.includes(String(r.row_id))} onChange={() => { setRowIds(toggle(rowIds, String(r.row_id))); setConfirmed(false) }} />{text(r.row_id)} · {text(r.exchange)}|{text(r.token)} · {text(r.quantity)} · identity {text(r.identity_verified)} · coverage {text(r.inventory_coverage)}</label>)}<ReferencePage label="inventory rows" ids={rowIds} offset={rowOffset} total={serverRows.length} onPage={setRowOffset} /></fieldset><fieldset><legend>Opening fills ({v.ledger ? 'user declared ledger' : 'server day report'})</legend>{fills.slice(fillOffset, fillOffset + pageSize).map((f, i) => <label key={i}><input type="checkbox" checked={fillIds.includes(String(f.fill_id))} disabled={fillIds.length >= 100 && !fillIds.includes(String(f.fill_id))} onChange={() => { setFillIds(toggle(fillIds, String(f.fill_id))); setConfirmed(false) }} />{text(f.fill_id)} · {text(f.contract_id)} · {text(f.side)} {text(f.quantity)} at {text(f.price)} · {text(f.executed_at)}</label>)}<ReferencePage label="opening fills" ids={fillIds} offset={fillOffset} total={fills.length} onPage={setFillOffset} /></fieldset><label><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />I explicitly confirm these selected opening fills and exact inventory rows.</label><button disabled={busy || !v.baseline || !v.portfolio || !rowIds.length || !confirmed} onClick={() => void safe(async () => { await loadAssociation('POST', { portfolio_evidence_id: v.portfolio, row_ids: rowIds, fill_ids: fillIds, confirm_executed: confirmed, costs_inr: moneyText(v.costs, true), lot_ledger_id: v.ledger || null }) })}>Associate explicit selection</button><button disabled={busy || !v.baseline} onClick={() => loadAssociation('GET')}>Load association history</button><Evidence value={association ?? 'No association selected'} /></section>
    <ActionForm title="Complete FIFO lot ledger import · user declared" action="Validate and import declared ledger" disabled={busy || !complete} onSubmit={() => void safe(async () => { const data = await request('/lot-ledger-imports', 'POST', { ...object(JSON.parse(ledger)), complete }); if (data !== undefined) { setImportResult(data); await loadAssociations() } })}><p>Schema/example below: flat zero opening inventory per selected contract; every BUY/SELL with contiguous sequence, unique fill ID, exact price/cost, offset timestamp. Coverage end must equal the server snapshot observation time. Newer snapshots make attribution unavailable until complete history is extended. Never broker-verified.</p><label>Complete ledger JSON<textarea rows={12} value={ledger} onChange={e => setLedger(e.target.value)} /></label><label><input type="checkbox" checked={complete} onChange={e => setComplete(e.target.checked)} />I declare all history from the flat opening inventory through coverage end is complete.</label></ActionForm>
    <ActionForm title="Equity and external cashflows · user declared" action="Import equity observations" disabled={busy} onSubmit={() => void safe(async () => { const observations = equity.map((r, i) => { if (!/^-?\d+(\.\d{1,12})?$/.test(r.external_flow_inr)) throw new Error('External flow must be signed decimal text.'); return { ...r, sequence: i, equity_inr: moneyText(r.equity_inr), complete: true, source: 'user_declared', flow_timing: 'before_valuation_at_prior_nav', currency: 'INR' } }); const data = await request('/equity-imports', 'POST', { observations }); if (data !== undefined) setImportResult(data) })}><p>Ordered complete series from sequence zero. First external flow must be zero. Subsequent signed deposits/withdrawals occur before valuation at prior NAV. Missing/unknown coverage cannot establish drawdown.</p>{equity.map((r, i) => <fieldset key={i}><legend>Observation {i}</legend><InputFields values={r} onChange={next => setEquity(equity.map((x, j) => j === i ? next : x))} specs={[{ key: 'observed_at', label: 'Observation timestamp with offset' }, { key: 'equity_inr', label: 'Equity INR' }, { key: 'external_flow_inr', label: 'External flow INR (signed)' }]} /></fieldset>)}<button type="button" disabled={equity.length >= 500} onClick={() => setEquity([...equity, { observed_at: '', equity_inr: '', external_flow_inr: '0' }])}>Add observation</button><button type="button" onClick={async () => { const data = await request('/equity-imports?limit=20&offset=0'); if (data !== undefined) setImportResult(data) }}>Load equity imports</button></ActionForm><Evidence value={importResult ?? 'No import result'} />
    <section className="op-panel"><h2>Risk observations</h2><Evidence value={risk ?? 'No observations loaded'} /><h2>In-app alerts</h2>{rows(alerts).map((a, i) => <article key={i}><Evidence value={a} /><button disabled={busy} onClick={async () => { await request(`/alerts/${a.id}/read`, 'POST'); await refresh() }}>Mark alert read</button><button disabled={busy} onClick={async () => { await request(`/alerts/${a.id}/acknowledge`, 'POST'); await refresh() }}>Acknowledge alert</button><button onClick={() => selectReport('alert', String(a.id))}>Explain saved alert</button></article>)}{!rows(alerts).length && <p>No alerts in this page.</p>}<button disabled={!offset} onClick={() => changeAlertPage(offset - pageSize)}>Previous alerts</button><span> Offset {offset} </span><button disabled={rows(alerts).length < pageSize} onClick={() => changeAlertPage(offset + pageSize)}>Next alerts</button></section>
  </>
}
