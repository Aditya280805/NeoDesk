import { useRef, useState } from 'react'
import { object, rows, text } from '@/lib/optionsPlatform'
import { ActionForm, choices, Evidence, Fields, InputFields } from './Forms'
import { useWorkspace } from './Workspace'

export default function Explanations({ selected }: { selected: { kind: string; id: string } }) {
  const { request, cancel, busy } = useWorkspace()
  const [v, setV] = useState<Fields>({ kind: selected.kind, id: selected.id, message: '' }), [reports, setReports] = useState<unknown>(), [answer, setAnswer] = useState<unknown>(), [conversation, setConversation] = useState('')
  const revision = useRef(0)
  const change = (next: Fields) => { if (next.kind !== v.kind || next.id !== v.id) { cancel('explanation'); cancel('explanation-reports'); revision.current++; setConversation(''); setAnswer(undefined); if (next.kind !== v.kind) { next.id = ''; setReports(undefined) } }; setV(next) }
  const paths: Record<string, string> = { strategy: 'analyses', scan: 'scans', alert: 'alerts', backtest: 'backtests' }
  async function explain() {
    const ticket = revision.current
    const result = await request('/explain', 'POST', { report_kind: v.kind, report_id: v.id, message: v.message, ...(conversation ? { conversation_id: conversation } : {}) }, 'explanation')
    if (result !== undefined && ticket === revision.current) { setAnswer(result); setConversation(String(object(result).conversation_id)) }
  }
  return <ActionForm title="Ask the options agent about one saved report" action="Explain selected saved report" disabled={busy || !v.kind || !v.id} onSubmit={() => void explain()}><p>The same options agent reads this selected immutable owner report and cites its exact evidence. Historical observations are not fresh market claims. Only this explicit action calls the model.</p><InputFields values={v} onChange={change} specs={[{ key: 'kind', label: 'Saved report type', options: choices('strategy', 'scan', 'alert', 'backtest') }]} /><button type="button" disabled={!v.kind} onClick={async () => { const ticket = revision.current; const result = await request(`/${paths[v.kind]}?limit=100&offset=0`, 'GET', undefined, 'explanation-reports'); if (result !== undefined && ticket === revision.current) setReports(result) }}>Load saved reports of selected type</button><InputFields values={v} onChange={change} specs={[{ key: 'id', label: 'Selected saved report', options: [{ value: v.id, label: v.id }].filter(o => o.value && !rows(reports).some(r => String(r.report_id ?? r.id) === o.value)).concat(rows(reports).filter(r => v.kind !== 'scan' && v.kind !== 'backtest' || ['completed', 'partial'].includes(String(r.status))).map(r => ({ value: String(r.id ?? r.report_id), label: `${text(r.report_id ?? r.id)} · ${text(r.status ?? r.current_outcome)}` }))) }, { key: 'message', label: 'Question about selected report', multiline: true }]} /><p>Selected immutable identity: {v.kind || 'none'} / {v.id || 'none'}. Changing selection starts a separate conversation.</p>{answer !== undefined && <section aria-live="polite"><h3>Saved-report explanation</h3><p>{text(object(answer).answer)}</p><h3>Citations and observation notice</h3><Evidence value={answer} /></section>}</ActionForm>
}
