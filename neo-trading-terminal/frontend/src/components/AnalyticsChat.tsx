import { FormEvent, useRef, useState } from 'react'
import { api, failure } from '@/lib/api'

type Context = { underlying: string; exchange: string; expiry: string | null }
type Stage = {
  role: string; interpretation: string; status: string
  evidence: Record<string, unknown>
  claims: { evidence_id: string; path: (string | number)[]; value: unknown }[]
}
type Result = {
  scope: 'analytics'; status: string; answer: string; stages: Stage[]
  continuation_id: string | null; continuations_exhausted?: boolean
  pending?: { role: string; tools: string[] }[]
}

export default function AnalyticsChat({ context }: { context: Context }) {
  const [question, setQuestion] = useState('')
  const [result, setResult] = useState<Result | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const inFlight = useRef(false)
  const action = useRef<string | null>(null)
  const requestQuestion = useRef('')

  async function run(resume: boolean) {
    if (inFlight.current || (!resume && !question.trim())) return
    inFlight.current = true
    setBusy(true)
    setError('')
    if (!resume) {
      requestQuestion.current = question.trim()
      action.current = null
      setResult(null)
    } else if (!action.current) action.current = crypto.randomUUID()
    try {
      const reply = await api<Result>('/options-agent/unified-chat', 'POST', {
        analytics_mode: true, message: requestQuestion.current, context,
        ...(resume ? { continuation_id: result?.continuation_id, continuation_action_id: action.current } : {}),
      })
      if (reply.scope !== 'analytics' || !Array.isArray(reply.stages)) throw new Error('Unexpected analytics response.')
      setResult(reply)
      action.current = null
    } catch (error) {
      setError(failure(error))
    } finally {
      inFlight.current = false
      setBusy(false)
    }
  }

  return <section className="panel" aria-label="Composite analytics">
    <h2>Composite analytics</h2>
    <p>Ask across options, portfolio analysis and risk. Each section shows its evidence and missing inputs.</p>
    <form onSubmit={(event: FormEvent) => { event.preventDefault(); void run(false) }}>
      <label>Analytics question
        <input value={question} maxLength={2000} disabled={busy} onChange={event => setQuestion(event.target.value)} />
      </label>
      <button disabled={busy || !question.trim()} type="submit">Analyze</button>
    </form>
    {busy && <p role="status">Processing the next analytics sections…</p>}
    {error && <p role="alert">{error}</p>}
    {result && <div aria-live="polite">
      <p>Status: {result.status}</p>
      {result.stages.map((stage, index) => <article key={`${stage.role}-${index}`}>
        <h3>{stage.role.replaceAll('_', ' ')}</h3>
        <p>{stage.interpretation}</p>
        <dl>{stage.claims.map((claim, index) => <div key={index}>
          <dt>{claim.path.join(' → ')}</dt><dd>{String(claim.value ?? 'Unavailable')} · evidence {claim.evidence_id}</dd>
        </div>)}</dl>
        <details><summary>Evidence, coverage and proposal candidates</summary><pre>{JSON.stringify(stage.evidence, null, 2)}</pre></details>
      </article>)}
      {!result.stages.length && <p>{result.answer}</p>}
      {result.pending?.map(task => <p key={task.role}>Pending: {task.role.replaceAll('_', ' ')} — {task.tools.join(', ')}</p>)}
      {result.continuation_id && <button disabled={busy} onClick={() => void run(true)}>Continue pending sections</button>}
      {result.continuations_exhausted && <p>The continuation limit was reached. Start a new analysis for remaining sections.</p>}
    </div>}
  </section>
}
