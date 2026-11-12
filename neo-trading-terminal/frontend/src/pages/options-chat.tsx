import Link from 'next/link'
import { FormEvent, useCallback, useEffect, useRef, useState } from 'react'
import { MessageCircle, RefreshCw, Send, ShieldCheck } from 'lucide-react'
import { ApiError, api, failure, money } from '@/lib/api'
import { watchVisibleSnapshots } from '@/lib/optionsMonitoring'
import PortfolioEvidence from '@/components/PortfolioEvidence'
import type { PortfolioSnapshot } from '@/lib/portfolioEvidence'
import { PortfolioRiskEnvelope, RiskReport, canPublish } from '@/lib/portfolioRisk'
import PortfolioRiskPanel from '@/components/PortfolioRiskPanel'
import PortfolioRiskSettings from '@/components/PortfolioRiskSettings'
import AnalyticsChat from '@/components/AnalyticsChat'

type ChatMode = 'chain' | 'portfolio' | 'risk' | 'auto'
type ConcreteScope = 'chain' | 'portfolio' | 'risk'
type Context = { underlying: string; exchange: string; expiry: string | null }
type Leg = { side: string; symbol: string; strike: number; ltp: number; volume: number | null; open_interest: number | null }
type Snapshot = {
  snapshot_id: string
  source: string
  retrieved_at: string
  expiry: string
  underlying: string
  rows: Leg[]
  limitations: string[]
  summary: { call_open_interest: number | null; put_open_interest: number | null; put_call_ratio: number | null }
}
type RiskSnapshot = {
  evidence_id: string
  risk_report?: RiskReport
}
type AgentStatus = {
  analytics_tools_enabled?: boolean
  analytics_composite_enabled?: boolean
  configured: boolean
  model_configured: boolean
  mcp_ready: boolean
  model: string
  read_only: boolean
  provider: string
  api_key_env: string
  setup_error: string | null
}
type Reply =
  | { scope: 'chain'; agent_id: string; conversation_id: string; answer: string; snapshot: Snapshot; created_at: string }
  | { scope: 'portfolio'; agent_id: string; conversation_id: string; answer: string; portfolio_snapshot: PortfolioSnapshot; evidence_ids: string[]; created_at: string }
  | { scope: 'risk'; agent_id: string; conversation_id: string; answer: string; risk_snapshot: RiskSnapshot; evidence_ids: string[]; risk_report_ids: string[]; created_at: string }
  | { scope: 'clarify'; agent_id: string; conversation_id: string | null; answer: string; created_at: string }
type Turn = Reply & { question: string }

const initialContext: Context = { underlying: 'NIFTY', exchange: 'nse_fo', expiry: null }

const MODE_META: Record<ChatMode, {
  label: string
  heading: string
  welcome: string
  thinking: string
  suggestions: string[]
}> = {
  chain: {
    label: 'Options and trading',
    heading: 'Ask your options and trading agent',
    welcome: 'A clearer view of your option chain.',
    thinking: 'Fetching the option chain and preparing your answer…',
    suggestions: [
      'Summarize this option chain.',
      'Which returned strikes have the highest open interest?',
      'Explain the put/call ratio and its limitations.',
    ],
  },
  portfolio: {
    label: 'Portfolio analysis',
    heading: 'Ask your portfolio analysis agent',
    welcome: 'A clearer view of your portfolio.',
    thinking: 'Fetching portfolio evidence and preparing your answer…',
    suggestions: [
      'Summarize my portfolio evidence.',
      'Which sections are unavailable?',
      'Explain the reported P&L and its limitations.',
    ],
  },
  risk: {
    label: 'Portfolio risk',
    heading: 'Ask your portfolio risk agent',
    welcome: 'Deterministic portfolio risk checks.',
    thinking: 'Evaluating your deterministic portfolio risk report…',
    suggestions: [
      'Evaluate my portfolio risk report against my active limits.',
      'Which risk checks cannot be assessed and why?',
      'Summarize the deterministic margin and exposure observations.',
    ],
  },
  auto: {
    label: 'Auto-select',
    heading: 'Ask the unified trading & portfolio router',
    welcome: 'Ask about an option chain, portfolio evidence, or portfolio risk.',
    thinking: 'Routing your question and preparing your answer…',
    suggestions: [
      'Summarize this option chain.',
      'Summarize my portfolio evidence.',
      'Evaluate my portfolio risk against my active policy.',
    ],
  },
}

const count = (value: number | null) => value == null ? 'Unavailable' : value.toLocaleString('en-IN', { maximumFractionDigits: 2 })
const timestamp = (value: string) => new Date(value).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', hour12: true })

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(item => typeof item === 'string')
}

const EXPECTED_AGENT_ID: Record<ConcreteScope | 'clarify', string> = {
  chain: 'options_trading_analysis',
  portfolio: 'portfolio_analysis',
  risk: 'portfolio_risk',
  clarify: 'master_router',
}

function sanitizePortfolioSnapshot(raw: PortfolioRiskEnvelope & { risk_inputs?: unknown }): PortfolioSnapshot {
  const { risk_report: _rr, risk_inputs: _ri, ...evidence } = raw
  return evidence
}

function hasPortfolioSectionsShape(sections: unknown): boolean {
  if (!isRecord(sections)) return false
  for (const name of ['holdings', 'positions', 'orders', 'funds'] as const) {
    const section = sections[name]
    if (section === undefined) continue
    if (
      !isRecord(section) ||
      !Array.isArray(section.issues) ||
      !isRecord(section.values) ||
      !isRecord(section.provenance) ||
      !Array.isArray(section.rows)
    ) {
      return false
    }
  }
  return true
}

function hasRiskReportShape(report: unknown): boolean {
  if (!isRecord(report)) return false
  return (
    typeof report.report_id === 'string' &&
    typeof report.evaluated_at === 'string' &&
    typeof report.calculation_version === 'string' &&
    typeof report.summary === 'string' &&
    typeof report.policy_revision === 'number' &&
    isRecord(report.coverage) &&
    Array.isArray(report.findings) &&
    report.findings.every(
      f =>
        isRecord(f) &&
        typeof f.code === 'string' &&
        typeof f.outcome === 'string' &&
        isStringArray(f.affected_row_ids) &&
        isStringArray(f.reason_codes)
    ) &&
    isRecord(report.observation_times) &&
    isStringArray(report.limitations)
  )
}

function hasChainSnapshotShape(snapshot: unknown): snapshot is Snapshot {
  return (
    isRecord(snapshot) &&
    Array.isArray(snapshot.rows) &&
    typeof snapshot.underlying === 'string' &&
    typeof snapshot.expiry === 'string' &&
    typeof snapshot.retrieved_at === 'string' &&
    isRecord(snapshot.summary) &&
    isStringArray(snapshot.limitations)
  )
}

function validateReply(
  raw: unknown,
  currentMode: ChatMode,
  activeScope: ConcreteScope | null,
  activeConversationId: string | null,
): Reply {
  if (
    !isRecord(raw) ||
    typeof raw.answer !== 'string' ||
    !raw.answer.trim() ||
    typeof raw.agent_id !== 'string' ||
    !raw.agent_id.trim() ||
    raw.read_only === false
  ) {
    throw new Error('Unexpected response format from options agent.')
  }
  if (currentMode === 'auto' && typeof raw.scope !== 'string') {
    throw new Error('Unified router response did not declare a valid scope.')
  }
  if (currentMode !== 'auto' && raw.scope !== undefined && raw.scope !== currentMode) {
    throw new Error('Specialist scope mismatch returned by server.')
  }
  const targetScope = currentMode === 'auto' ? raw.scope : currentMode
  const createdAt = typeof raw.created_at === 'string' ? raw.created_at : ''

  if (targetScope === 'clarify') {
    if (currentMode !== 'auto' || raw.agent_id !== EXPECTED_AGENT_ID.clarify) {
      throw new Error('Unexpected clarification response from server.')
    }
    if (
      'snapshot' in raw ||
      'portfolio_snapshot' in raw ||
      'risk_snapshot' in raw ||
      'evidence_ids' in raw ||
      'snapshot_ids' in raw ||
      'risk_report_ids' in raw ||
      'report_ids' in raw ||
      'report' in raw ||
      'risk_report' in raw
    ) {
      throw new Error('Clarification response must not include specialist evidence.')
    }
    const rawCid = raw.conversation_id
    if (activeConversationId === null) {
      if (rawCid != null) {
        throw new Error('Initial clarification response must not create a specialist conversation.')
      }
    } else if (rawCid != null && (typeof rawCid !== 'string' || !rawCid.trim() || rawCid !== activeConversationId)) {
      throw new Error('Clarification response altered the active conversation.')
    }
    return {
      scope: 'clarify',
      agent_id: raw.agent_id,
      conversation_id: typeof rawCid === 'string' ? rawCid : null,
      answer: raw.answer,
      created_at: createdAt,
    }
  }

  if (targetScope !== 'chain' && targetScope !== 'portfolio' && targetScope !== 'risk') {
    throw new Error('Unsupported specialist scope returned by server.')
  }
  if (currentMode === 'auto' && activeScope !== null && targetScope !== activeScope) {
    throw new Error('Conversation scope changed unexpectedly. Start a new chat.')
  }
  if (raw.agent_id !== EXPECTED_AGENT_ID[targetScope]) {
    throw new Error('Unexpected specialist agent returned by server.')
  }
  if (typeof raw.conversation_id !== 'string' || !raw.conversation_id.trim()) {
    throw new Error('Specialist response is missing a conversation identifier.')
  }

  if (targetScope === 'chain') {
    const snap = raw.snapshot
    if (!hasChainSnapshotShape(snap)) {
      throw new Error('Options chain response is missing required snapshot evidence.')
    }
    return {
      scope: 'chain',
      agent_id: raw.agent_id,
      conversation_id: raw.conversation_id,
      answer: raw.answer,
      snapshot: snap as Snapshot,
      created_at: createdAt,
    }
  }

  if (targetScope === 'portfolio') {
    const ps = raw.portfolio_snapshot
    if (
      'risk_report' in raw ||
      'risk_report_ids' in raw ||
      'risk_inputs' in raw ||
      'risk_snapshot' in raw ||
      !isRecord(ps) ||
      'risk_report' in ps ||
      'risk_inputs' in ps ||
      typeof ps.evidence_id !== 'string' ||
      !isRecord(ps.summary) ||
      !hasPortfolioSectionsShape(ps.sections) ||
      !isStringArray(ps.limitations) ||
      !isStringArray(raw.evidence_ids) ||
      raw.evidence_ids.length === 0
    ) {
      throw new Error('Portfolio analysis response is missing or mixed with invalid evidence.')
    }
    return {
      scope: 'portfolio',
      agent_id: raw.agent_id,
      conversation_id: raw.conversation_id,
      answer: raw.answer,
      portfolio_snapshot: sanitizePortfolioSnapshot(ps as PortfolioSnapshot & { risk_inputs?: unknown }),
      evidence_ids: raw.evidence_ids,
      created_at: createdAt,
    }
  }

  const rs = raw.risk_snapshot
  if (
    'portfolio_snapshot' in raw ||
    !isRecord(rs) ||
    'holdings' in rs ||
    'positions' in rs ||
    'funds' in rs ||
    'orders' in rs ||
    'sections' in rs ||
    typeof rs.evidence_id !== 'string' ||
    !hasRiskReportShape(rs.risk_report) ||
    !isStringArray(raw.evidence_ids) ||
    raw.evidence_ids.length === 0 ||
    !isStringArray(raw.risk_report_ids) ||
    raw.risk_report_ids.length === 0
  ) {
    throw new Error('Portfolio risk response is missing required risk report evidence.')
  }
  return {
    scope: 'risk',
    agent_id: raw.agent_id,
    conversation_id: raw.conversation_id,
    answer: raw.answer,
    risk_snapshot: rs as RiskSnapshot,
    evidence_ids: raw.evidence_ids,
    risk_report_ids: raw.risk_report_ids,
    created_at: createdAt,
  }
}

export default function OptionsChat() {
  const [policyRevision, setPolicyRevision] = useState<number | undefined>(undefined)
  const [mode, setMode] = useState<ChatMode>('chain')
  const [resolvedScope, setResolvedScope] = useState<ConcreteScope | null>(null)
  const [portfolioEvidence, setPortfolioEvidence] = useState<PortfolioSnapshot | null>(null)
  const [riskSnapshot, setRiskSnapshot] = useState<RiskSnapshot | null>(null)
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
  const [scopeChangeConflict, setScopeChangeConflict] = useState(false)
  const [snapshotError, setSnapshotError] = useState('')
  const [now, setNow] = useState(0)

  const activeChatVersion = useRef<number | null>(null)
  const activeSnapshotVersion = useRef<number | null>(null)
  const mounted = useRef(true)
  const revision = useRef(0)
  const bottom = useRef<HTMLDivElement>(null)

  const effectiveScope: ConcreteScope | null = mode === 'auto' ? resolvedScope : mode

  useEffect(() => {
    mounted.current = true
    api<AgentStatus>('/options-agent/status')
      .then(s => { if (mounted.current) setStatus(s) })
      .catch(e => { if (mounted.current) setError(failure(e)) })

    const expired = () => {
      revision.current += 1
      activeChatVersion.current = null
      activeSnapshotVersion.current = null
      setBusy(false)
      setLoadingSnapshot(false)
      setPolicyRevision(undefined)
      setMonitoring(false)
      setResolvedScope(null)
      setPortfolioEvidence(null)
      setRiskSnapshot(null)
      setSnapshot(null)
      setSnapshotError('')
      setTurns([])
      setConversationId(null)
      setScopeChangeConflict(false)
      setError('')
    }
    window.addEventListener('neodesk:session-expired', expired)
    const timer = setInterval(() => setNow(Date.now()), 10000)

    return () => {
      mounted.current = false
      revision.current += 1
      activeChatVersion.current = null
      activeSnapshotVersion.current = null
      clearInterval(timer)
      window.removeEventListener('neodesk:session-expired', expired)
    }
  }, [])

  const refresh = useCallback(async () => {
    const targetScope = mode === 'auto' ? resolvedScope : mode
    if (!targetScope) return
    if (activeChatVersion.current !== null || activeSnapshotVersion.current !== null) return

    const version = revision.current
    activeSnapshotVersion.current = version
    setLoadingSnapshot(true)

    try {
      if (targetScope === 'portfolio') {
        const result = await api<PortfolioRiskEnvelope & { risk_inputs?: unknown }>('/options-agent/portfolio/snapshot', 'POST', {})
        if (canPublish(version, revision.current, mounted.current)) {
          if (!isRecord(result) || typeof result.evidence_id !== 'string' || !isRecord(result.summary) || !hasPortfolioSectionsShape(result.sections) || !isStringArray(result.limitations)) {
            throw new Error('Portfolio snapshot evidence is incomplete.')
          }
          setPortfolioEvidence(sanitizePortfolioSnapshot(result))
          setSnapshotError('')
          setNow(Date.now())
        }
      } else if (targetScope === 'risk') {
        const result = await api<PortfolioRiskEnvelope>('/options-agent/portfolio/snapshot', 'POST', {})
        if (canPublish(version, revision.current, mounted.current)) {
          if (!isRecord(result) || typeof result.evidence_id !== 'string' || !hasRiskReportShape(result.risk_report)) {
            throw new Error('Portfolio risk snapshot is missing risk report evidence.')
          }
          setRiskSnapshot({ evidence_id: result.evidence_id, risk_report: result.risk_report })
          setSnapshotError('')
          setNow(Date.now())
        }
      } else {
        const result = await api<Snapshot>('/options-agent/snapshot', 'POST', context)
        if (canPublish(version, revision.current, mounted.current)) {
          if (!hasChainSnapshotShape(result)) {
            throw new Error('Options chain snapshot evidence is incomplete.')
          }
          setSnapshot(result)
          setSnapshotError('')
          setNow(Date.now())
        }
      }
    } catch (e) {
      if (canPublish(version, revision.current, mounted.current)) {
        setSnapshotError(failure(e))
        setMonitoring(false)
      }
    } finally {
      if (activeSnapshotVersion.current === version) {
        activeSnapshotVersion.current = null
        if (mounted.current) setLoadingSnapshot(false)
      }
    }
  }, [context, mode, resolvedScope])

  useEffect(() => {
    if (!monitoring) return
    return watchVisibleSnapshots(() => { void refresh() }, setVisible)
  }, [monitoring, refresh])

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [turns, busy])

  function resetConversationState(clearQuestion: boolean) {
    revision.current += 1
    activeChatVersion.current = null
    activeSnapshotVersion.current = null
    setBusy(false)
    setLoadingSnapshot(false)
    setResolvedScope(null)
    setPortfolioEvidence(null)
    setRiskSnapshot(null)
    setSnapshot(null)
    setSnapshotError('')
    setTurns([])
    setConversationId(null)
    setMonitoring(false)
    setError('')
    setScopeChangeConflict(false)
    if (clearQuestion) setQuestion('')
  }

  function changeMode(nextMode: ChatMode) {
    if (nextMode !== 'risk') setPolicyRevision(undefined)
    resetConversationState(false)
    setMode(nextMode)
  }

  function changeContext(next: Context) {
    resetConversationState(false)
    setContext(next)
  }

  function startNewChat() {
    if (mode === 'auto') setPolicyRevision(undefined)
    resetConversationState(false)
  }

  async function ask(message: string) {
    const trimmed = message.trim()
    if (
      !trimmed ||
      activeChatVersion.current !== null ||
      activeSnapshotVersion.current !== null ||
      !status?.configured ||
      (effectiveScope === 'chain' && !context.underlying.trim())
    ) {
      return
    }

    const version = revision.current
    activeChatVersion.current = version
    setBusy(true)
    setError('')
    setScopeChangeConflict(false)

    try {
      let path = '/options-agent/chat'
      let body: Record<string, unknown> = {
        ...context,
        message: trimmed,
        ...(conversationId ? { conversation_id: conversationId } : {}),
      }

      if (mode === 'portfolio') {
        path = '/options-agent/portfolio/chat'
        body = { message: trimmed, ...(conversationId ? { conversation_id: conversationId } : {}) }
      } else if (mode === 'risk') {
        path = '/options-agent/portfolio/risk/chat'
        body = { message: trimmed, ...(conversationId ? { conversation_id: conversationId } : {}) }
      } else if (mode === 'auto') {
        path = '/options-agent/unified-chat'
        const trimmedUnderlying = context.underlying.trim()
        body = {
          message: trimmed,
          ...(trimmedUnderlying ? { context: { ...context, underlying: trimmedUnderlying } } : {}),
          ...(conversationId ? { conversation_id: conversationId } : {}),
        }
      }

      const raw = await api<unknown>(path, 'POST', body)
      if (!canPublish(version, revision.current, mounted.current)) return

      const result = validateReply(raw, mode, resolvedScope, conversationId)

      if (result.scope === 'clarify') {
        if (result.conversation_id) setConversationId(result.conversation_id)
        setTurns(previous => [...previous, { ...result, question: trimmed }])
        setQuestion('')
        return
      }

      setConversationId(result.conversation_id)
      if (mode === 'auto') {
        setResolvedScope(result.scope)
      }

      if (result.scope === 'portfolio') {
        setPortfolioEvidence(result.portfolio_snapshot)
      } else if (result.scope === 'risk') {
        setRiskSnapshot(result.risk_snapshot)
      } else {
        setSnapshot(result.snapshot)
      }

      setSnapshotError('')
      setNow(Date.now())
      setTurns(previous => [...previous, { ...result, question: trimmed }])
      setQuestion('')
    } catch (e) {
      if (canPublish(version, revision.current, mounted.current)) {
        const isScopeConflict = e instanceof ApiError && e.status === 409 && e.code === 'conversation_scope_changed'
        setScopeChangeConflict(isScopeConflict)
        setError(failure(e))
        setMonitoring(false)
      }
    } finally {
      if (activeChatVersion.current === version) {
        activeChatVersion.current = null
        if (mounted.current) setBusy(false)
      }
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault()
    void ask(question)
  }

  const stale = effectiveScope === 'chain' && snapshot && now - new Date(snapshot.retrieved_at).getTime() > 90000
  const disabled = busy || loadingSnapshot
  const refreshDisabled = disabled || !effectiveScope || (effectiveScope === 'chain' && !context.underlying.trim())
  const showMarketControls = mode === 'chain' || (mode === 'auto' && (resolvedScope === null || resolvedScope === 'chain'))
  const strikes = snapshot ? Array.from(new Set(snapshot.rows.map(r => r.strike))).sort((a, b) => a - b) : []
  const activeMeta = effectiveScope ? MODE_META[effectiveScope] : MODE_META[mode]
  const modeMeta = MODE_META[mode]

  const hasAsideData =
    effectiveScope === 'portfolio' ? Boolean(portfolioEvidence)
      : effectiveScope === 'risk' ? Boolean(riskSnapshot)
        : effectiveScope === 'chain' ? Boolean(snapshot)
          : false

  const asideTitle =
    effectiveScope === 'portfolio' ? 'Portfolio evidence'
      : effectiveScope === 'risk' ? 'Portfolio risk'
        : 'Market snapshot'

  const questionContextLabel =
    effectiveScope === 'portfolio' ? 'your portfolio'
      : effectiveScope === 'risk' ? 'portfolio risk'
        : effectiveScope === 'chain' ? context.underlying || 'options'
          : 'options, portfolio, or risk'

  return <>
    <div className="page-heading">
      <div>
        <p className="eyebrow">YOUR OPTIONS RESEARCH COMPANION</p>
        <h1>Options chat<span className="accent">.</span></h1>
        <p>Ask about premiums, volume, open interest, portfolio evidence, or deterministic portfolio risk.</p>
      </div>
      <span className="badge"><ShieldCheck size={13} /> READ ONLY</span>
    </div>

    <section className="panel options-chat-controls" aria-label="Options context">
      <div className="toolbar">
        <label>
          Scope
          <select aria-label="Chat scope" value={mode} onChange={e => changeMode(e.target.value as ChatMode)}>
            <option value="chain">Options and trading</option>
            <option value="portfolio">Portfolio analysis</option>
            <option value="risk">Portfolio risk</option>
            <option value="auto">Auto-select</option>
          </select>
        </label>

        {showMarketControls && <>
          <label>
            Underlying
            <input
              value={context.underlying}
              maxLength={40}
              disabled={disabled}
              onChange={e => changeContext({ ...context, underlying: e.target.value.toUpperCase() })}
              placeholder="NIFTY or RELIANCE"
            />
          </label>
          <label>
            Exchange
            <select
              value={context.exchange}
              disabled={disabled}
              onChange={e => changeContext({ ...context, exchange: e.target.value, expiry: null })}
            >
              <option value="nse_fo">NSE F&O</option>
              <option value="bse_fo">BSE F&O</option>
            </select>
          </label>
          <label>
            Expiry
            <input
              value={context.expiry || ''}
              maxLength={40}
              disabled={disabled}
              onChange={e => changeContext({ ...context, expiry: e.target.value || null })}
              placeholder="Nearest available"
            />
          </label>
        </>}

        <button type="button" disabled={refreshDisabled} onClick={() => void refresh()}>
          <RefreshCw size={14} />{loadingSnapshot ? 'Fetching…' : 'Refresh snapshot'}
        </button>

        <label className="options-monitor-toggle">
          <input
            type="checkbox"
            checked={monitoring}
            disabled={refreshDisabled}
            onChange={e => {
              setMonitoring(e.target.checked)
              if (e.target.checked) void refresh()
            }}
          />
          Refresh every minute
        </label>
      </div>
      <p className="options-context-note">Changing the scope or market starts a new conversation. Refresh runs while this page is open and visible.</p>
      <p className="options-context-note" role="status">Monitoring: {monitoring ? visible ? 'active · refresh every 60 seconds' : 'paused · page hidden' : 'off'}</p>
    </section>

    {effectiveScope === 'risk' && <PortfolioRiskSettings onRevision={setPolicyRevision} />}

    {status?.analytics_tools_enabled && status?.analytics_composite_enabled && <AnalyticsChat key={JSON.stringify(context)} context={context} />}

    <div className="options-chat-layout">
      <section className="panel options-conversation" aria-label="Options conversation">
        <div className="section-heading">
          <h2><MessageCircle size={18} /> {activeMeta.heading}</h2>
          <button
            type="button"
            disabled={disabled || (!turns.length && !scopeChangeConflict && !conversationId)}
            onClick={startNewChat}
          >
            New chat
          </button>
        </div>

        {status && !status.mcp_ready && (
          <div className="options-setup-note" role="status">
            <b>Options monitoring is temporarily unavailable.</b>
            <p>The options data service is not ready. Ask the server operator to check the service configuration.</p>
          </div>
        )}

        {status && !status.model_configured && (
          <div className="options-setup-note" role="status">
            <b>AI replies need server configuration.</b>
            <p>{status.setup_error || `Add ${status.api_key_env} to the server configuration and restart the backend.`} You can still refresh Kotak snapshots here. Your broker key and AI key serve different purposes.</p>
          </div>
        )}

        <div className="options-messages" role="log" aria-label="Conversation messages" aria-live="polite">
          {!turns.length && (
            <div className="options-chat-welcome">
              <span className="options-chat-symbol"><MessageCircle size={28} /></span>
              <h2>{modeMeta.welcome}</h2>
              <p>Choose a specialist or Auto-select, then ask a question. Each answer cites its own Kotak evidence; cached observations retain their original source time.</p>
              <div className="options-suggestions">
                {modeMeta.suggestions.map(s => (
                  <button key={s} type="button" disabled={disabled || !status?.configured || (effectiveScope === 'chain' && !context.underlying.trim())} onClick={() => { setQuestion(s); void ask(s) }}>
                    {s}<span>↗</span>
                  </button>
                ))}
              </div>
              <small>Snapshot analysis only. Exchange freshness is unverified. No orders. This page refresh is separate from opt-in platform background alerts.</small>
            </div>
          )}

          {turns.map((turn, index) => (
            <div className="options-turn" key={index}>
              <div className="options-message options-user"><small>YOU</small><p>{turn.question}</p></div>
              <div className="options-message options-assistant">
                <small>OPTIONS AGENT · {turn.agent_id} · scope: {turn.scope}</small>
                <p>{turn.answer}</p>
                {turn.scope === 'portfolio' && (
                  <div className="options-evidence">
                    <PortfolioEvidence snapshot={turn.portfolio_snapshot} />
                    <p>Cited evidence: {turn.evidence_ids.join(', ')}</p>
                  </div>
                )}
                {turn.scope === 'risk' && (
                  <div className="options-evidence">
                    <PortfolioRiskPanel report={turn.risk_snapshot.risk_report} currentRevision={policyRevision} />
                    <p>Cited evidence: {turn.evidence_ids.join(', ')} · Risk reports: {turn.risk_report_ids.join(', ')}</p>
                  </div>
                )}
                {turn.scope === 'chain' && (
                  <div className="options-evidence">
                    Kotak snapshot · {turn.snapshot.underlying} · {turn.snapshot.expiry}
                    <br />
                    Retrieved {timestamp(turn.snapshot.retrieved_at)} IST · exchange freshness unverified
                  </div>
                )}
              </div>
            </div>
          ))}

          {busy && <p className="options-thinking" role="status">{activeMeta.thinking}</p>}
          <div ref={bottom} />
        </div>

        {error && (
          <div className="error options-chat-error" role="alert">
            <span>{error}</span>
            {scopeChangeConflict && (
              <button type="button" onClick={startNewChat}>New chat</button>
            )}
          </div>
        )}

        <form className="options-composer" onSubmit={submit}>
          <label htmlFor="options-question">Your question about {questionContextLabel}</label>
          <div>
            <textarea
              id="options-question"
              value={question}
              maxLength={2000}
              rows={2}
              disabled={busy}
              onChange={e => setQuestion(e.target.value)}
              placeholder="What does open interest tell us about these strikes?"
            />
            <button type="submit" className="primary" aria-label="Send question" disabled={disabled || !status?.configured || !question.trim() || (effectiveScope === 'chain' && !context.underlying.trim())}>
              <Send size={17} />
            </button>
          </div>
          <small>Read-only analysis · No trade execution · Conversations are saved privately to your account</small>
        </form>
      </section>

      <aside className="panel options-snapshot" aria-label="Latest option snapshot">
        <div className="section-heading">
          <h2>{asideTitle}</h2>
          <span className={`badge ${stale || snapshotError ? 'amber' : ''}`}>
            {snapshotError ? 'REFRESH FAILED' : stale ? 'OLDER SNAPSHOT' : hasAsideData ? 'KOTAK REST' : 'NO DATA'}
          </span>
        </div>

        {snapshotError && (
          <div className="error options-chat-error" role="alert">
            <span>{snapshotError}{hasAsideData && ' The previous snapshot is retained below.'}</span>
          </div>
        )}

        {effectiveScope === null && (
          <div className="empty-state">Ask a question in Auto-select or choose a specific specialist to view matching evidence.</div>
        )}

        {effectiveScope === 'portfolio' && (
          portfolioEvidence
            ? <PortfolioEvidence snapshot={portfolioEvidence} />
            : <div className="empty-state">Refresh to retrieve portfolio evidence. Missing values remain unavailable.</div>
        )}

        {effectiveScope === 'risk' && (
          riskSnapshot
            ? <PortfolioRiskPanel report={riskSnapshot.risk_report} currentRevision={policyRevision} stale={!!snapshotError} />
            : <div className="empty-state">Refresh or ask a risk question to evaluate your deterministic portfolio risk report.</div>
        )}

        {effectiveScope === 'chain' && (
          !snapshot ? (
            <div className="empty-state">
              Your snapshot will appear here.
              <small>Connect Kotak in <Link href="/connections/" className="text-link">Connections</Link>, then refresh. No sample chain is substituted.</small>
            </div>
          ) : <>
            <div className="options-snapshot-meta">
              <b>{snapshot.underlying} · {snapshot.expiry}</b>
              <span>Retrieved {timestamp(snapshot.retrieved_at)} IST</span>
              <small>Exchange freshness unverified</small>
            </div>
            <div className="options-summary">
              <div><small>Call OI · returned strikes</small><b>{count(snapshot.summary.call_open_interest)}</b></div>
              <div><small>Put OI · returned strikes</small><b>{count(snapshot.summary.put_open_interest)}</b></div>
              <div><small>Partial-chain put/call ratio</small><b>{count(snapshot.summary.put_call_ratio)}</b></div>
            </div>
            <div className="table-scroll options-snapshot-table">
              <table>
                <caption>Premiums, volume and OI · returned strikes</caption>
                <thead>
                  <tr><th>Call OI</th><th>Call volume</th><th>Call LTP</th><th>Strike</th><th>Put LTP</th><th>Put volume</th><th>Put OI</th></tr>
                </thead>
                <tbody>
                  {strikes.map(strike => {
                    const call = snapshot.rows.find(r => r.strike === strike && r.side === 'CALL')
                    const put = snapshot.rows.find(r => r.strike === strike && r.side === 'PUT')
                    return (
                      <tr key={strike}>
                        <td>{count(call?.open_interest ?? null)}</td>
                        <td>{count(call?.volume ?? null)}</td>
                        <td>{money(call?.ltp)}</td>
                        <td>{count(strike)}</td>
                        <td>{money(put?.ltp)}</td>
                        <td>{count(put?.volume ?? null)}</td>
                        <td>{count(put?.open_interest ?? null)}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
            <details className="options-limitations">
              <summary>Data coverage and limitations</summary>
              <ul>{snapshot.limitations.map(text => <li key={text}>{text}</li>)}</ul>
            </details>
          </>
        )}
      </aside>
    </div>
  </>
}
