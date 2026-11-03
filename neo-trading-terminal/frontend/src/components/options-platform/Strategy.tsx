import { SetStateAction, useState } from 'react'
import { integer, moneyText, object, rows, text } from '@/lib/optionsPlatform'
import { ActionForm, choices, Evidence, Fields, InputFields } from './Forms'
import { useWorkspace } from './Workspace'

export const costKeys = ['opening_fees_inr', 'expiry_fees_inr', 'stock_slippage_per_unit', 'call_slippage_per_unit', 'put_slippage_per_unit']
export const costs = (v: Fields) => Object.fromEntries(costKeys.map(k => [k, moneyText(v[k] ?? '', true)]))
export default function Strategy() {
  const { request, cancel, busy, selectReport } = useWorkspace()
  const [market, setMarket] = useState<unknown>(), [report, setReport] = useState<unknown>(), [saved, setSaved] = useState<unknown>()
  const [portfolio, setPortfolio] = useState<unknown>(), [localError, setLocalError] = useState('')
  const [context, setContextValues] = useState<Fields>({ underlying: 'NIFTY', exchange: 'nse_fo', expiry: '' })
  const [v, setValues] = useState<Fields>({ mode: 'hypothetical', kind: 'covered_call', quantity: '', quote_max_age_seconds: '120', name: '' })
  const setContext = (next: Fields) => { cancel('/market-snapshot'); cancel('/analyses'); setContextValues(next); setMarket(undefined); setReport(undefined); setSaved(undefined) }
  const setV = (next: SetStateAction<Fields>) => { cancel('/analyses'); cancel('/baselines'); setValues(previous => { const result = typeof next === 'function' ? next(previous) : next; return result.mode !== previous.mode ? { ...result, stock_contract_id: '', call_contract_id: '', put_contract_id: '', holding_row_id: '' } : result }) }
  async function loadMarket() {
    const data = await request('/market-snapshot', 'POST', { ...context, expiry: context.expiry || null })
    if (data !== undefined) { setMarket(data); setReport(undefined); setSaved(undefined); setV(x => ({ ...x, stock_contract_id: '', call_contract_id: '', put_contract_id: '', holding_row_id: '' })) }
  }
  const evidence = object(market), contracts = rows(evidence.contracts)
  const contractChoices = (kind: string) => contracts.filter(c => c.kind === kind).map(c => ({ value: String(c.instrument_id), label: `${c.instrument_id} · ${text(c.symbol)} · ${text(c.strike)} · ${text(c.expiry)} · identity ${text(c.identity_verified)}` }))
  const holdings = Object.values(object(object(object(portfolio).snapshot).sections)).flatMap(s => rows(object(s).rows))
  async function analyze() {
    try {
      setLocalError('')
      const data = await request('/analyses', 'POST', { kind: v.kind, mode: v.mode, evidence_id: evidence.evidence_id, stock_contract_id: v.stock_contract_id, call_contract_id: v.call_contract_id, put_contract_id: v.kind === 'collar' ? v.put_contract_id : null, holding_row_id: v.mode === 'owned' ? v.holding_row_id : null, quantity: integer(v.quantity), acquisition_cost_per_share: moneyText(v.acquisition_cost_per_share ?? '', true), costs: costs(v), criteria: { capital_limit_inr: moneyText(v.capital_limit_inr ?? '', true), maximum_loss_inr: moneyText(v.maximum_loss_inr ?? '', true), require_broker_margin: v.require_broker_margin === 'yes' }, quote_max_age_seconds: integer(v.quote_max_age_seconds, 1, 86400) })
      if (data !== undefined) { setReport(data); setSaved(undefined) }
    } catch (e) { setLocalError((e as Error).message) }
  }
  return <><ActionForm title="Acquire server market evidence" action="Fetch market evidence" onSubmit={() => void loadMarket()} disabled={busy}><InputFields values={context} onChange={setContext} specs={[{ key: 'underlying', label: 'Underlying' }, { key: 'exchange', label: 'Exchange', options: choices('nse_fo', 'bse_fo') }, { key: 'expiry', label: 'Expiry', optional: true }]} /><p>Contracts below come only from this server response. Unverified identities and stale quotes can yield theoretical or unavailable analysis.</p><Evidence value={market ?? 'No server evidence selected'} /></ActionForm>
    {localError && <p role="alert">{localError}</p>}
    <ActionForm title="Covered call or collar" action="Analyze selected contracts" disabled={busy || !evidence.evidence_id} onSubmit={() => void analyze()}><InputFields values={v} onChange={next => { if (next.mode !== v.mode) next = { ...next, holding_row_id: '' }; if (next.kind !== v.kind) next = { ...next, put_contract_id: '' }; setV(next) }} specs={[
      { key: 'mode', label: 'Position basis', options: choices('owned', 'hypothetical') }, { key: 'kind', label: 'Strategy', options: choices('covered_call', 'collar') },
      { key: 'stock_contract_id', label: 'Equity contract', options: contractChoices('equity') }, { key: 'call_contract_id', label: 'Short call contract', options: contractChoices('call') },
      ...(v.kind === 'collar' ? [{ key: 'put_contract_id', label: 'Protective put contract', options: contractChoices('put') }] : []),
      ...(v.mode === 'owned' ? [{ key: 'holding_row_id', label: 'Server holding row', options: holdings.map(r => ({ value: String(r.row_id), label: `${r.row_id} · ${r.exchange}|${r.token} · quantity ${text(r.available_quantity)}` })) }] : []),
      { key: 'quantity', label: 'Quantity (units)' }, { key: 'acquisition_cost_per_share', label: 'Acquisition cost per share INR', optional: true },
      ...costKeys.map(key => ({ key, label: key.replaceAll('_', ' '), optional: true })), { key: 'capital_limit_inr', label: 'Capital limit INR', optional: true }, { key: 'maximum_loss_inr', label: 'Maximum downside INR', optional: true }, { key: 'require_broker_margin', label: 'Require broker margin', options: choices('yes', 'no'), optional: true }, { key: 'quote_max_age_seconds', label: 'Maximum quote age seconds' }
    ]} />{v.mode === 'owned' && <button type="button" disabled={busy} onClick={async () => { const data = await request('/association-evidence', 'POST'); if (data !== undefined) setPortfolio(data) }}>Fetch owner holding rows</button>}<p>Blank assumptions stay unset. Enter explicit zero for no cost. Monetary amounts are sent as decimal strings.</p></ActionForm>
    <section className="op-panel"><h2>Analysis, basis and scenarios</h2><Evidence value={report ?? 'No analysis yet'} />{Boolean(object(report).report_id) && <><button onClick={() => selectReport('strategy', String(object(report).report_id))}>Explain this saved analysis</button><ActionForm title="Save immutable baseline" action="Save baseline" disabled={busy} onSubmit={async () => { const data = await request('/baselines', 'POST', { analysis_id: object(report).report_id, name: v.name }); if (data !== undefined) setSaved(data) }}><InputFields values={v} onChange={setV} specs={[{ key: 'name', label: 'Baseline name' }]} /></ActionForm></>}<Evidence value={saved ?? 'No baseline saved'} /></section>
  </>
}
