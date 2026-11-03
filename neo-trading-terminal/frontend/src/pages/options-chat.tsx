import Link from 'next/link'

import { FormEvent, useCallback, useEffect, useRef, useState } from 'react'

import { MessageCircle, RefreshCw, Send, ShieldCheck } from 'lucide-react'

import { api, failure, money } from '@/lib/api'

import { watchVisibleSnapshots } from '@/lib/optionsMonitoring'



import PortfolioEvidence from '@/components/PortfolioEvidence'

import { PortfolioRiskEnvelope, canPublish } from '@/lib/portfolioRisk'
import PortfolioRiskPanel from '@/components/PortfolioRiskPanel'
import PortfolioRiskSettings from '@/components/PortfolioRiskSettings'



type Context = { underlying: string; exchange: string; expiry: string | null }

type Leg = { side: string; symbol: string; strike: number; ltp: number; volume: number | null; open_interest: number | null }

type Snapshot = {

  snapshot_id: string; source: string; retrieved_at: string; expiry: string; underlying: string

  rows: Leg[]; limitations: string[]

  summary: { call_open_interest: number | null; put_open_interest: number | null; put_call_ratio: number | null }

}

type AgentStatus = { configured: boolean; model_configured: boolean; mcp_ready: boolean; model: string; read_only: boolean;

  provider: string; api_key_env: string; setup_error: string | null }

type Reply = { scope: 'chain'; conversation_id: string; answer: string; snapshot: Snapshot; created_at: string } | { scope: 'portfolio'; conversation_id: string; answer: string; portfolio_snapshot: PortfolioRiskEnvelope; evidence_ids: string[]; risk_report_ids?: string[]; created_at: string }

type Turn = Reply & { question: string }

const initialContext: Context = { underlying: 'NIFTY', exchange: 'nse_fo', expiry: null }

const suggestions = ['Summarize this option chain.', 'Which returned strikes have the highest open interest?', 'Explain the put/call ratio and its limitations.']

const count = (value: number | null) => value == null ? 'Unavailable' : value.toLocaleString('en-IN', { maximumFractionDigits: 2 })

const timestamp = (value: string) => new Date(value).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', hour12: true })



export default function OptionsChat() {

  const [policyRevision, setPolicyRevision] = useState<number | undefined>(undefined)

  const [scope, setScope] = useState<'chain' | 'portfolio'>('chain')

  const [portfolioSnapshot, setPortfolioRiskEnvelope] = useState<PortfolioRiskEnvelope | null>(null)

  const [context, setContext] = useState<Context>(initialContext)

  const [status, setStatus] = useState<AgentStatus | null>(null)

  const [snapshot, setSnapshot] = useState<Snapshot | null>(null)

  const [turns, setTurns] = useState<Turn[]>([])

  const [conversationId, setConversationId] = useState<string | null>(null)

  const [question, setQuestion] = useState('')

  const [busy, setBusy] = useState(false)

  const [loadingSnapshot, setLoadingSnapshot] = useState(false)

  const [monitoring, setMonitoring] = useState(false)

  const [visible, setVisible] = useState(true)

  const [error, setError] = useState('')

  const [snapshotError, setSnapshotError] = useState('')

  const [now, setNow] = useState(0)

  const inFlight = useRef(false)

  const mounted = useRef(true)

  const revision = useRef(0)

  const bottom = useRef<HTMLDivElement>(null)



  useEffect(() => {

    mounted.current = true

    api<AgentStatus>('/options-agent/status').then(s => { if (mounted.current) setStatus(s) })

      .catch(e => { if (mounted.current) setError(failure(e)) })

    const expired = () => { revision.current += 1; setPolicyRevision(undefined); setMonitoring(false); setPortfolioRiskEnvelope(null); setSnapshot(null); setTurns([]); setConversationId(null) }
    window.addEventListener('neodesk:session-expired', expired)
    const timer = setInterval(() => setNow(Date.now()), 10000)

    return () => { mounted.current = false; revision.current += 1; clearInterval(timer); window.removeEventListener('neodesk:session-expired', expired) }

  }, [])



  const refresh = useCallback(async () => {

    if (inFlight.current) return

    const version = revision.current

    inFlight.current = true

    setLoadingSnapshot(true)

    try {

      if (scope === 'portfolio') {

        const result = await api<PortfolioRiskEnvelope>('/options-agent/portfolio/snapshot', 'POST', {})

        if (canPublish(version, revision.current, mounted.current)) { setPortfolioRiskEnvelope(result); setSnapshotError(''); setNow(Date.now()) }

      } else {

        const result = await api<Snapshot>('/options-agent/snapshot', 'POST', context)

        if (canPublish(version, revision.current, mounted.current)) { setSnapshot(result); setSnapshotError(''); setNow(Date.now()) }

      }

    } catch (e) {

      if (canPublish(version, revision.current, mounted.current)) { setSnapshotError(failure(e)); setMonitoring(false) }

    } finally {

      inFlight.current = false

      if (mounted.current) setLoadingSnapshot(false)

    }

  }, [context, scope])



  useEffect(() => {

    if (!monitoring) return

    return watchVisibleSnapshots(() => { void refresh() }, setVisible)

  }, [monitoring, refresh])



  useEffect(() => { bottom.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }) }, [turns, busy])



  function changeContext(next: Context) {

    revision.current += 1

    setContext(next); setPortfolioRiskEnvelope(null); setQuestion(''); setSnapshot(null); setSnapshotError(''); setTurns([])

    setConversationId(null); setMonitoring(false); setError('')

  }



  async function ask(message: string) {

    const trimmed = message.trim()

    if (!trimmed || inFlight.current || !status?.configured) return

    const version = revision.current

    inFlight.current = true

    setBusy(true); setError('')

    try {

      const result = await api<Reply>(scope === 'portfolio' ? '/options-agent/portfolio/chat' : '/options-agent/chat', 'POST', { ...(scope === 'chain' ? context : {}), message: trimmed, conversation_id: conversationId })

      if (!mounted.current || version !== revision.current) return

      setConversationId(result.conversation_id)

      if ('portfolio_snapshot' in result) setPortfolioRiskEnvelope(result.portfolio_snapshot)

      else setSnapshot(result.snapshot)

      setSnapshotError(''); setNow(Date.now())

      setTurns(previous => [...previous, { ...result, scope, question: trimmed } as Turn])

      setQuestion('')

    } catch (e) {

      if (canPublish(version, revision.current, mounted.current)) { setError(failure(e)); setMonitoring(false) }

    }

    finally { inFlight.current = false; if (mounted.current) setBusy(false) }

  }



  function submit(event: FormEvent) { event.preventDefault(); void ask(question) }

  const stale = snapshot && now - new Date(snapshot.retrieved_at).getTime() > 90000

  const disabled = busy || loadingSnapshot

  const strikes = snapshot ? Array.from(new Set(snapshot.rows.map(r => r.strike))).sort((a, b) => a - b) : []



  return <>

    <div className="page-heading"><div><p className="eyebrow">YOUR OPTIONS RESEARCH COMPANION</p>

      <h1>Options chat<span className="accent">.</span></h1>

      <p>Ask about premiums, volume and open interest in your selected option chain.</p>

    </div><span className="badge"><ShieldCheck size={13} /> READ ONLY</span></div>



    <section className="panel options-chat-controls" aria-label="Options context">

      <div className="toolbar">

        <label>Scope<select aria-label="Chat scope" value={scope} onChange={e => { changeContext(context); setScope(e.target.value as 'chain' | 'portfolio') }}><option value="chain">Option chain</option><option value="portfolio">Portfolio</option></select></label>

        {scope === 'chain' && <>

        <label>Underlying<input value={context.underlying} maxLength={40} disabled={disabled}

          onChange={e => changeContext({ ...context, underlying: e.target.value.toUpperCase() })} placeholder="NIFTY or RELIANCE" /></label>

        <label>Exchange<select value={context.exchange} disabled={disabled}

          onChange={e => changeContext({ ...context, exchange: e.target.value, expiry: null })}>

          <option value="nse_fo">NSE F&O</option><option value="bse_fo">BSE F&O</option></select></label>

        <label>Expiry<input value={context.expiry || ''} maxLength={40} disabled={disabled}

          onChange={e => changeContext({ ...context, expiry: e.target.value || null })} placeholder="Nearest available" /></label>

        </>}

        <button disabled={disabled || (scope === 'chain' && !context.underlying.trim())} onClick={() => void refresh()}><RefreshCw size={14} />{loadingSnapshot ? 'Fetching…' : 'Refresh snapshot'}</button>

        <label className="options-monitor-toggle"><input type="checkbox" checked={monitoring} disabled={disabled || (scope === 'chain' && !context.underlying.trim())}

          onChange={e => { setMonitoring(e.target.checked); if (e.target.checked) void refresh() }} />Refresh every minute</label>

      </div>

      <p className="options-context-note">Changing the scope or market starts a new conversation. Refresh runs while this page is open and visible.</p>

      <p className="options-context-note" role="status">Monitoring: {monitoring ? visible ? 'active · refresh every 60 seconds' : 'paused · page hidden' : 'off'}</p>

    </section>



    {scope === 'portfolio' && <PortfolioRiskSettings onRevision={setPolicyRevision}/>}

    <div className="options-chat-layout">

      <section className="panel options-conversation" aria-label="Options conversation">

        <div className="section-heading"><h2><MessageCircle size={18} /> Ask your {scope === 'portfolio' ? 'portfolio' : 'options'} agent</h2>

          <button disabled={disabled || !turns.length} onClick={() => { setTurns([]); setConversationId(null); setError('') }}>New chat</button></div>

        {status && !status.mcp_ready && <div className="options-setup-note" role="status"><b>Options monitoring is temporarily unavailable.</b>

          <p>The options data service is not ready. Ask the server operator to check the service configuration.</p></div>}

        {status && !status.model_configured && <div className="options-setup-note" role="status"><b>AI replies need server configuration.</b>

          <p>{status.setup_error || `Add ${status.api_key_env} to the server configuration and restart the backend.`} You can still refresh Kotak snapshots here. Your broker key and AI key serve different purposes.</p></div>}

        <div className="options-messages" role="log" aria-label="Conversation messages" aria-live="polite">

          {!turns.length && <div className="options-chat-welcome"><span className="options-chat-symbol"><MessageCircle size={28} /></span>

            <h2>A clearer view of your {scope === 'portfolio' ? 'portfolio' : 'option chain'}.</h2><p>Choose a scope, then ask a question. Each answer cites its own Kotak evidence; cached observations retain their original source time.</p>

            <div className="options-suggestions">{(scope === 'portfolio' ? ['Summarize my portfolio evidence.', 'Which sections are unavailable?', 'Explain the reported P&L and its limitations.'] : suggestions).map(s => <button key={s} disabled={disabled || !status?.configured} onClick={() => { setQuestion(s); void ask(s) }}>{s}<span>↗</span></button>)}</div>

            <small>Snapshot analysis only. Exchange freshness is unverified. No orders. This page refresh is separate from opt-in platform background alerts.</small></div>}

          {turns.map((turn, index) => <div className="options-turn" key={index}>

            <div className="options-message options-user"><small>YOU</small><p>{turn.question}</p></div>

            <div className="options-message options-assistant"><small>OPTIONS AGENT</small><p>{turn.answer}</p>

              {turn.scope === 'portfolio' ? <div className="options-evidence"><PortfolioEvidence snapshot={turn.portfolio_snapshot}/><PortfolioRiskPanel report={turn.portfolio_snapshot.risk_report} currentRevision={policyRevision}/><p>Cited evidence: {turn.evidence_ids.join(', ')}</p></div> : <div className="options-evidence">Kotak snapshot · {turn.snapshot.underlying} · {turn.snapshot.expiry}<br />Retrieved {timestamp(turn.snapshot.retrieved_at)} IST · exchange freshness unverified</div>}</div>

          </div>)}

          {busy && <p className="options-thinking" role="status">{scope === 'portfolio' ? 'Fetching portfolio evidence and preparing your answer…' : 'Fetching the option chain and preparing your answer…'}</p>}

          <div ref={bottom} />

        </div>

        {error && <p className="error options-chat-error" role="alert">{error}</p>}

        <form className="options-composer" onSubmit={submit}>

          <label htmlFor="options-question">Your question about {scope === 'portfolio' ? 'your portfolio' : context.underlying || 'options'}</label>

          <div><textarea id="options-question" value={question} maxLength={2000} rows={2} disabled={busy}

            onChange={e => setQuestion(e.target.value)} placeholder="What does open interest tell us about these strikes?" />

            <button className="primary" aria-label="Send question" disabled={disabled || !status?.configured || !question.trim()}><Send size={17} /></button></div>

          <small>Read-only analysis · No trade execution · Conversations are saved privately to your account</small>

        </form>

      </section>



      <aside className="panel options-snapshot" aria-label="Latest option snapshot">

        <div className="section-heading"><h2>{scope === 'portfolio' ? 'Portfolio evidence' : 'Market snapshot'}</h2><span className={`badge ${stale || snapshotError ? 'amber' : ''}`}>{snapshotError ? 'REFRESH FAILED' : stale ? 'OLDER SNAPSHOT' : snapshot || portfolioSnapshot ? 'KOTAK REST' : 'NO DATA'}</span></div>

        {snapshotError && <p className="error options-chat-error" role="alert">{snapshotError}{(snapshot || portfolioSnapshot) && ' The previous snapshot is retained below.'}</p>}

        {scope === 'portfolio' ? portfolioSnapshot ? <><PortfolioEvidence snapshot={portfolioSnapshot}/><PortfolioRiskPanel report={portfolioSnapshot.risk_report} currentRevision={policyRevision} stale={!!snapshotError}/></> : <div className="empty-state">Refresh to retrieve portfolio evidence. Missing values remain unavailable.</div> : !snapshot ? <div className="empty-state">Your snapshot will appear here.<small>Connect Kotak in <Link href="/connections/" className="text-link">Connections</Link>, then refresh. No sample chain is substituted.</small></div> : <>

          <div className="options-snapshot-meta"><b>{snapshot.underlying} · {snapshot.expiry}</b><span>Retrieved {timestamp(snapshot.retrieved_at)} IST</span><small>Exchange freshness unverified</small></div>

          <div className="options-summary"><div><small>Call OI · returned strikes</small><b>{count(snapshot.summary.call_open_interest)}</b></div>

            <div><small>Put OI · returned strikes</small><b>{count(snapshot.summary.put_open_interest)}</b></div>

            <div><small>Partial-chain put/call ratio</small><b>{count(snapshot.summary.put_call_ratio)}</b></div></div>

          <div className="table-scroll options-snapshot-table"><table><caption>Premiums, volume and OI · returned strikes</caption><thead><tr><th>Call OI</th><th>Call volume</th><th>Call LTP</th><th>Strike</th><th>Put LTP</th><th>Put volume</th><th>Put OI</th></tr></thead><tbody>

            {strikes.map(strike => {

              const call = snapshot.rows.find(r => r.strike === strike && r.side === 'CALL')

              const put = snapshot.rows.find(r => r.strike === strike && r.side === 'PUT')

              return <tr key={strike}><td>{count(call?.open_interest ?? null)}</td><td>{count(call?.volume ?? null)}</td><td>{money(call?.ltp)}</td><td>{count(strike)}</td><td>{money(put?.ltp)}</td><td>{count(put?.volume ?? null)}</td><td>{count(put?.open_interest ?? null)}</td></tr>

            })}

          </tbody></table></div>

          <details className="options-limitations"><summary>Data coverage and limitations</summary><ul>{snapshot.limitations.map(text => <li key={text}>{text}</li>)}</ul></details>

        </>}

      </aside>

    </div>

  </>

}

