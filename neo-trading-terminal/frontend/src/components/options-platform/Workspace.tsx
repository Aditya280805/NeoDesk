import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import { useTerminal } from '@/components/Layout'
import { object, PlatformRequests } from '@/lib/optionsPlatform'
import { Evidence } from './Forms'
import Strategy from './Strategy'
import Monitoring from './Monitoring'
import Jobs from './Jobs'
import Explanations from './Explanations'

type Request = (path: string, method?: string, body?: unknown, channel?: string) => Promise<unknown>
const Context = createContext<{ request: Request; cancel: (channel: string) => void; busy: boolean; selectReport: (kind: string, id: string) => void }>({ request: async () => undefined, cancel: () => {}, busy: false, selectReport: () => {} })
export const useWorkspace = () => useContext(Context)
export default function Workspace() {
  const { user } = useTerminal()
  return user ? <OwnedWorkspace key={user.id} /> : <p role="status">Sign in to open your private options workspace.</p>
}
function OwnedWorkspace() {
  const [tab, setTab] = useState('Data readiness'), [errors, setErrors] = useState<Record<string, string>>({}), [pending, setPending] = useState(0)
  const [capabilities, setCapabilities] = useState<unknown>(), [selected, setSelected] = useState({ kind: '', id: '' })
  const client = useRef<PlatformRequests | null>(null), alive = useRef(false), epoch = useRef(0)
  const operations = useRef(new Map<string, number>())
  const resourceOperations = useRef(new Map<string, number>())
  const conflicts = useRef(new Set<string>())
  const cancel = useCallback((channel: string) => { client.current?.cancel(channel); operations.current.set(channel, (operations.current.get(channel) ?? 0) + 1) }, [])
  const request: Request = useCallback(async (path, method = 'GET', body, channel = path) => {
    if (!alive.current || !client.current) return undefined
    const resource = path.split('?')[0]
    if (method !== 'GET' && conflicts.current.has(resource)) return undefined
    const generation = epoch.current, ticket = (operations.current.get(channel) ?? 0) + 1
    const resourceTicket = (resourceOperations.current.get(resource) ?? 0) + 1
    resourceOperations.current.set(resource, resourceTicket)
    operations.current.set(channel, ticket); setPending(n => n + 1)
    const current = () => alive.current && generation === epoch.current && ticket === operations.current.get(channel)
    try {
      const result = await client.current.request(path, method, body, channel)
      if (!current()) return undefined
      if (resourceOperations.current.get(resource) === resourceTicket) {
        if (method === 'GET') conflicts.current.delete(resource)
        if (!conflicts.current.has(resource)) setErrors(previous => {
          if (!(resource in previous)) return previous
          const next = { ...previous }
          delete next[resource]
          return next
        })
      }
      return result
    } catch (e) {
      if (current() && resourceOperations.current.get(resource) === resourceTicket
        && !(e instanceof DOMException && e.name === 'AbortError')) {
        const message = e instanceof Error ? e.message : 'Request unavailable'
        if (message.startsWith('Conflict:')) {
          conflicts.current.add(resource)
          setErrors(previous => ({ ...previous, [resource]: message }))
        } else if (!conflicts.current.has(resource)) {
          setErrors(previous => ({ ...previous, [resource]: message }))
        }
      }
      return undefined
    } finally { if (alive.current && generation === epoch.current) setPending(n => Math.max(0, n - 1)) }
  }, [])
  useEffect(() => {
    alive.current = true; client.current = new PlatformRequests()
    const end = () => { epoch.current++; client.current?.invalidate(); conflicts.current.clear(); setErrors({}); setPending(0) }
    window.addEventListener('neodesk:session-expired', end)
    const advance = () => { epoch.current += 1 }
    return () => { alive.current = false; advance(); client.current?.invalidate(); window.removeEventListener('neodesk:session-expired', end) }
  }, [])
  const loadCapabilities = useCallback(async () => { const result = await request('/capabilities'); if (result !== undefined) setCapabilities(result) }, [request])
  useEffect(() => { const initial = setTimeout(() => void loadCapabilities(), 0); return () => clearTimeout(initial) }, [loadCapabilities])
  const tabs = ['Data readiness', 'Strategies', 'Monitoring', 'Scanner', 'Backtesting', 'Explanations']
  const failedResources = Object.entries(errors)
  return <Context.Provider value={{ request, cancel, busy: pending > 0, selectReport: (kind, id) => { cancel('explanation'); cancel('explanation-reports'); setSelected({ kind, id }); setTab('Explanations') } }}><main className="options-platform">
    <div className="page-heading"><div><p className="eyebrow">EVIDENCE · ANALYSIS · FOLLOW THROUGH</p><h1>Options workspace</h1><p>Private saved evidence, explicit assumptions and independently running jobs. No order placement.</p></div></div>
    <nav aria-label="Options workspace sections" className="op-tabs">{tabs.map(t => <button key={t} aria-current={tab === t ? 'page' : undefined} onClick={() => setTab(t)}>{t}</button>)}</nav>
    {failedResources.length > 0 && <div role="alert" tabIndex={-1} className="op-error"><strong>Request unavailable.</strong><ul>{failedResources.map(([resource, message]) => <li key={resource}>{resource} · {message}</li>)}</ul><p>Prior evidence for these resources remains stale until successfully refreshed. Your draft is retained.</p></div>}
    <p role="status" aria-live="polite">{pending > 0 ? 'Working…' : failedResources.length ? 'Retained evidence may be stale.' : 'Ready. Missing values remain unavailable; zero is displayed as zero.'}</p>
    {tab === 'Data readiness' && <section className="op-panel"><h2>Adapter data readiness</h2><p>This reviewed capability inventory is not a live broker verification. Fetching market evidence requires a valid session and does not establish executable prices.</p><button onClick={() => void loadCapabilities()}>Refresh readiness</button><Evidence value={capabilities ?? 'Not loaded'} /><p>{String(object(capabilities).notice ?? 'Unsupported or unverified fields prevent an executable assessment. Historical imports are separately labelled.')}</p></section>}
    <div hidden={tab !== 'Strategies'}><Strategy /></div>
    <div hidden={tab !== 'Monitoring'}><Monitoring visible={tab === 'Monitoring'} /></div>
    <div hidden={tab !== 'Scanner'}><Jobs kind="scans" visible={tab === 'Scanner'} /></div>
    <div hidden={tab !== 'Backtesting'}><Jobs kind="backtests" visible={tab === 'Backtesting'} /></div>
    <div hidden={tab !== 'Explanations'}><Explanations key={`${selected.kind}:${selected.id}`} selected={selected} /></div>
  </main></Context.Provider>
}
