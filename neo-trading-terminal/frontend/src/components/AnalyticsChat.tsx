import { FormEvent, useEffect, useRef, useState } from 'react'
import { api, failure } from '@/lib/api'

type Context = { underlying: string; exchange: string; expiry: string | null }
type Stage = {
  role: string; interpretation: string; status: string
  evidence: Record<string, unknown>
  claims: { evidence_id: string; path: (string | number)[]; value: unknown }[]
}
type Result = {
  read_only: true
  scope: 'analytics'; status: string; answer: string; stages: Stage[]
  continuation_id: string | null; continuations_exhausted?: boolean
  selected_proposal?: { proposal_id: string; template: string; legs: { side: string; contract_id: string; quantity: number }[] } | null
  pending?: { role: string; tools: string[] }[]
}

function evidenceSummary(value: unknown) {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return null
  const record = value as Record<string, unknown>
  const reasons = record.unavailable_reasons
  return { status: typeof record.status === 'string' ? record.status : 'Coverage unknown',
    missing: typeof reasons === 'object' && reasons !== null && !Array.isArray(reasons)
      ? Object.entries(reasons).filter((entry): entry is [string, string] => typeof entry[1] === 'string') : [] }
}

export default function AnalyticsChat({ context }: { context: Context }) {
  const [question, setQuestion] = useState('')
  const [result, setResult] = useState<Result | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const inFlight = useRef(false)
  const action = useRef<string | null>(null)
  const requestQuestion = useRef('')
  const [historicalInput, setHistoricalInput] = useState('')
  const [savedImports, setSavedImports] = useState<{ dataset_id: string }[]>([])
  const requestInput = useRef<unknown>(null)
  const revision = useRef(0)
  const mounted = useRef(true)

  useEffect(() => {
    mounted.current = true
    const expired = () => {
      revision.current += 1
      inFlight.current = false
      action.current = null
      requestQuestion.current = ''
      requestInput.current = null
      setQuestion('')
      setHistoricalInput('')
      setSavedImports([])
      setResult(null)
      setBusy(false)
      setError('')
    }
    window.addEventListener('neodesk:session-expired', expired)
    return () => {
      mounted.current = false
      revision.current += 1
      window.removeEventListener('neodesk:session-expired', expired)
    }
  }, [])

  async function run(resume: boolean) {
    if (inFlight.current || (!resume && !question.trim())) return
    inFlight.current = true
    setBusy(true)
    setError('')
    const version = revision.current
    if (!resume) {
      try {
        requestInput.current = historicalInput.trim() ? JSON.parse(historicalInput) : null
      } catch {
        setError('Historical input must be valid JSON.')
        inFlight.current = false
        setBusy(false)
        return
      }
      requestQuestion.current = question.trim()
      action.current = null
      setResult(null)
    } else if (!action.current) action.current = crypto.randomUUID()
    try {
      const reply = await api<Result>('/options-agent/unified-chat', 'POST', {
        analytics_mode: true, message: requestQuestion.current, context,
        ...(requestInput.current ? { historical_input: requestInput.current } : {}),
        ...(resume ? { continuation_id: result?.continuation_id, continuation_action_id: action.current } : {}),
      })
      if (!mounted.current || version !== revision.current) return
      if (reply.scope !== 'analytics' || reply.read_only !== true || !Array.isArray(reply.stages)) throw new Error('Unexpected analytics response.')
      setResult(reply)
      action.current = null
    } catch (error) {
      if (mounted.current && version === revision.current) setError(failure(error))
    } finally {
      if (mounted.current && version === revision.current) {
        inFlight.current = false
        setBusy(false)
      }
    }
  }

  return <section className="panel analytics-panel" aria-label="Composite analytics">
    <h2>Composite analytics</h2>
    <p>Ask across options, portfolio analysis and risk. Each section shows its evidence and missing inputs.</p>
    <p>A ledger is optional. Use market and current-position analysis without uploading one. Cash-flow performance needs additional account history and valuations.</p>
    <form onSubmit={(event: FormEvent) => { event.preventDefault(); void run(false) }}>
      <label>Analytics question
        <input value={question} maxLength={2000} disabled={busy} onChange={event => setQuestion(event.target.value)} />
      </label>
      <details><summary>Optional historical inputs</summary>
        <button type="button" disabled={busy} onClick={async () => {
          const expectedRevision = revision.current
          try {
            const response = await api<{ items: { dataset_id: string }[] }>('/options-agent/imports')
            if (mounted.current && expectedRevision === revision.current) setSavedImports(response.items)
          } catch (error) { if (expectedRevision === revision.current) setError(failure(error)) }
        }}>Show saved imports</button>
        <p>Delete removes the original saved import. Previously generated reports may retain derived summaries.</p>
        {savedImports.map(item => <div key={item.dataset_id}>
          <span>Import {item.dataset_id.slice(0, 8)}</span>
          <button type="button" disabled={busy} onClick={async () => {
            if (!window.confirm('Permanently delete this saved import? Derived reports are retained.')) return
            const expectedRevision = revision.current
            try {
              await api(`/options-agent/imports/${item.dataset_id}`, 'DELETE')
              if (mounted.current && expectedRevision === revision.current) setSavedImports(items => items.filter(row => row.dataset_id !== item.dataset_id))
            } catch (error) { if (expectedRevision === revision.current) setError(failure(error)) }
          }}>Delete import</button>
        </div>)}
        <label>Optional ledger CSV (up to 1 MiB)
          <input type="file" accept=".csv,text/csv" disabled={busy} onChange={async event => {
            const file = event.target.files?.[0]
            const selectedRevision = revision.current
            event.target.value = ''
            if (!file) return
            if (file.size > 1048576) { setError('Ledger must be at most 1 MiB.'); return }
            try {
              const text = await file.text()
              if (!mounted.current || selectedRevision !== revision.current) return
              if (text.replace(/^\uFEFF/, '').split(/\r?\n/, 1)[0] !== 'date,type,amount_paise') throw new Error('Use the CSV columns date,type,amount_paise.')
              const existing = historicalInput.trim() ? JSON.parse(historicalInput) : {
                context, observed_at: new Date().toISOString(), provenance: 'user ledger upload', licence: 'uploaded by account owner',
              }
              setHistoricalInput(JSON.stringify({ ...existing, ledger_csv: text }, null, 2))
              setResult(null)
              setError('')
            } catch (error) { setError(failure(error)) }
          }} />
        </label>
        <p>Standard CSV format: date,type,amount_paise. Dates use YYYY-MM-DD; amounts are nonnegative integer paise. Types: DEPOSIT, WITHDRAWAL, CHARGE, SETTLEMENT_CREDIT, SETTLEMENT_DEBIT. Remove personal identifiers. The upload is submitted with your next question and stored privately with your account. Clear the text below to remove it before submission.</p>
        <label>Declared historical input JSON
          <textarea value={historicalInput} maxLength={2000000} disabled={busy} onChange={event => setHistoricalInput(event.target.value)} />
        </label>
        <p>Include provenance, licence, matching market context and dated OHLCV or cash-flow-adjusted returns. Imported observations are labelled unverified and retain their original dates.</p>
      </details>
      <button disabled={busy || !question.trim()} type="submit">Analyze</button>
    </form>
    {busy && <p role="status">Processing the next analytics sections…</p>}
    {error && <p role="alert">{error}</p>}
    {result && <div aria-live="polite">
      <p>Status: {result.status}</p>
      {result.selected_proposal && <article aria-label="Selected hypothetical proposal">
        <h3>Selected hypothetical proposal</h3>
        <p>{result.selected_proposal.template.replaceAll('_', ' ')} · {result.selected_proposal.proposal_id}</p>
        <ul>{result.selected_proposal.legs.map(leg => <li key={leg.contract_id}>{leg.side} {leg.quantity} · {leg.contract_id}</li>)}</ul>
        <p>Post-proposal costs and combined-account risk require captured supporting inputs. Read the downstream coverage before assessing this proposal.</p>
      </article>}
      {result.stages.map((stage, index) => <article key={`${stage.role}-${index}`}>
        <h3>{stage.role.replaceAll('_', ' ')}</h3>
        <p>{stage.interpretation}</p>
        <dl>{stage.claims.map((claim, index) => <div key={index}>
          <dt>{claim.path.join(' → ')}</dt><dd>{String(claim.value ?? 'Unavailable')} · evidence {claim.evidence_id}</dd>
        </div>)}</dl>
        {Object.entries(stage.evidence).map(([name, value]) => {
          const info = evidenceSummary(value)
          return info && <div className="analytics-evidence-summary" key={name}>
            <strong>{name.replaceAll('_', ' ')} · {info.status}</strong>
            {info.missing.length > 0 && <ul>{info.missing.slice(0, 8).map(([field, reason]) => <li key={field}>{field}: {reason}</li>)}</ul>}
            {info.missing.length > 8 && <small>{info.missing.length - 8} more coverage notes in the evidence details.</small>}
          </div>
        })}
        <details><summary>Evidence, coverage and proposal candidates</summary><pre tabIndex={0} aria-label="Captured analytics evidence JSON">{JSON.stringify(stage.evidence, null, 2)}</pre></details>
      </article>)}
      {!result.stages.length && <p>{result.answer}</p>}
      {result.pending?.map(task => <p key={task.role}>Pending: {task.role.replaceAll('_', ' ')} — {task.tools.join(', ')}</p>)}
      {result.continuation_id && <button disabled={busy} onClick={() => void run(true)}>Continue pending sections</button>}
      {result.continuations_exhausted && <p>The continuation limit was reached. Start a new analysis for remaining sections.</p>}
    </div>}
  </section>
}
