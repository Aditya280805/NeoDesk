import { useCallback, useEffect, useRef, useState } from 'react'
import { integer, moneyText, object, rows, text, watchPlatformJob } from '@/lib/optionsPlatform'
import { ActionForm, choices, Evidence, Fields, InputFields } from './Forms'
import { useWorkspace } from './Workspace'
import HistoricalImport from './HistoricalImport'
import BacktestForm from './BacktestForm'
import { costKeys, costs } from './Strategy'

export default function Jobs({ kind, visible }: { kind: 'scans' | 'backtests'; visible: boolean }) {
  const { request, cancel, busy, selectReport } = useWorkspace(), scan = kind === 'scans'
  const [v, setV] = useState<Fields>({ strategy: 'covered_call', scope: 'hypothetical', quote_max_age_seconds: '120' }), [error, setError] = useState('')
  const [jobs, setJobs] = useState<unknown>(), [selected, setSelectedValue] = useState(''), [job, setJob] = useState<unknown>(), [offset, setOffset] = useState(0), [datasets, setDatasets] = useState<unknown>()
  const selection = useRef({ id: '', operation: 0, cancelling: false })
  const setSelected = (id: string, initial?: unknown) => {
    selection.current = { id, operation: 0, cancelling: false }
    cancel(`${kind}-selected`)
    cancel(`${kind}-cancel`)
    setSelectedValue(id)
    setJob(initial)
  }
  const refresh = useCallback(async () => { const data = await request(`/${kind}?limit=20&offset=${offset}`, 'GET', undefined, `${kind}-list`); if (data !== undefined) setJobs(data) }, [request, kind, offset])
  const refreshJob = useCallback(async () => {
    const context = selection.current
    if (!context.id || context.cancelling) return
    const operation = ++context.operation
    const data = await request(`/${kind}/${context.id}`, 'GET', undefined, `${kind}-selected`)
    if (selection.current === context && context.operation === operation && data !== undefined) setJob(data)
  }, [request, kind])
  async function cancelJob() {
    const context = selection.current
    if (!context.id || context.cancelling) return
    context.cancelling = true
    context.operation++
    cancel(`${kind}-selected`)
    try {
      const data = await request(`/${kind}/${context.id}/cancel`, 'POST', undefined, `${kind}-cancel`)
      if (selection.current === context && data !== undefined) setJob(data)
    } finally {
      context.cancelling = false
    }
  }
  useEffect(() => { const initial = setTimeout(() => { if (visible && document.visibilityState === 'visible') void refresh() }, 0); return () => clearTimeout(initial) }, [visible, refresh])
  useEffect(() => {
    if (!visible || !selected) return
    return watchPlatformJob(() => void refreshJob(), () => cancel(`${kind}-selected`))
  }, [visible, selected, refreshJob, cancel, kind])
  async function startScan() {
    try {
      setError('')
      const payload = { capital_inr: moneyText(v.capital_inr), strategy: v.strategy, scope: v.scope, min_expiry_days: integer(v.min_expiry_days, 1, 3660), max_expiry_days: integer(v.max_expiry_days, 1, 3660), minimum_volume: moneyText(v.minimum_volume), minimum_open_interest: moneyText(v.minimum_open_interest), minimum_depth: moneyText(v.minimum_depth), maximum_relative_spread: moneyText(v.maximum_relative_spread), maximum_loss_inr: moneyText(v.maximum_loss_inr), quote_max_age_seconds: integer(v.quote_max_age_seconds, 1, 86400), costs: costs(v) }
      if (Object.entries(payload.costs).some(([k, value]) => value === null && (v.strategy === 'collar' || k !== 'put_slippage_per_unit'))) throw new Error('Explicit costs and slippage are required. Enter zero where applicable.')
      const data = await request('/scans', 'POST', payload)
      await started(data)
    } catch (e) { setError((e as Error).message) }
  }
  const started = async (data: unknown) => { if (data !== undefined) { setSelected(String(object(data).id), data); await refresh() } }
  const loadDatasets = async () => { const data = await request('/historical-imports?limit=100&offset=0'); if (data !== undefined) setDatasets(data) }
  return <>{error && <p role="alert">{error}</p>}{scan ? <ActionForm title="Explicit scanner criteria" action="Start scan" disabled={busy} onSubmit={() => void startScan()}><p>One verified lot per candidate. Ranking is net horizon yield within comparable groups, not a risk score. Coverage and exclusions remain visible; missing data cannot pass criteria.</p><InputFields values={v} onChange={setV} specs={[
    { key: 'strategy', label: 'Scan strategy', options: choices('covered_call', 'collar') }, { key: 'scope', label: 'Scan scope', options: choices('owned', 'hypothetical') }, { key: 'capital_inr', label: 'Capital INR' }, { key: 'min_expiry_days', label: 'Minimum expiry days' }, { key: 'max_expiry_days', label: 'Maximum expiry days' }, { key: 'minimum_volume', label: 'Minimum volume' }, { key: 'minimum_open_interest', label: 'Minimum open interest' }, { key: 'minimum_depth', label: 'Minimum depth' }, { key: 'maximum_relative_spread', label: 'Maximum relative spread (fraction)' }, { key: 'maximum_loss_inr', label: 'Maximum loss INR' }, { key: 'quote_max_age_seconds', label: 'Scanner maximum quote age seconds' }, ...costKeys.filter(k => v.strategy === 'collar' || k !== 'put_slippage_per_unit').map(key => ({ key, label: `Scan ${key.replaceAll('_', ' ')}` }))
  ]} /></ActionForm> : <><HistoricalImport onImported={() => void loadDatasets()} /><button onClick={() => void loadDatasets()}>Load validated historical imports</button><Evidence value={datasets ?? 'No historical imports loaded'} /><BacktestForm datasets={rows(datasets)} onStarted={started} /></>}
    <section className="op-panel"><h2>{scan ? 'Scan' : 'Backtest'} jobs and immutable results</h2><p>Visible-page polling every 10 seconds. Backend jobs continue independently. Retained results after an error are stale until refreshed.</p><button onClick={() => void refresh()}>Refresh {scan ? 'scan' : 'backtest'} jobs</button><label>Select {scan ? 'scan' : 'backtest'} job<select value={selected} onChange={e => setSelected(e.target.value)}><option value="">Select…</option>{rows(jobs).map(j => <option key={String(j.id)} value={String(j.id)}>{text(j.id)} · {text(j.status)}</option>)}</select></label><button disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 20))}>Previous jobs</button><span> Offset {offset} </span><button disabled={rows(jobs).length < 20} onClick={() => setOffset(offset + 20)}>Next jobs</button><button disabled={!selected} onClick={() => void refreshJob()}>Refresh selected job</button><button disabled={busy || !selected || ['completed', 'partial', 'failed', 'cancelled'].includes(String(object(job).status))} onClick={() => cancelJob()}>Cancel selected job</button><Evidence value={job ?? 'No job selected'} />{Boolean(object(job).report) && <button onClick={() => selectReport(scan ? 'scan' : 'backtest', selected)}>Explain saved {scan ? 'scan' : 'backtest'} result</button>}</section>
  </>
}
