import { apiBase } from './api'

export type RecordData = { [key: string]: unknown }
export const object = (value: unknown): RecordData => value && typeof value === 'object' && !Array.isArray(value) ? value as RecordData : {}
export const rows = (value: unknown): RecordData[] => Array.isArray(value) ? value.map(object) : []
export const text = (value: unknown) => value == null ? 'Unavailable' : typeof value === 'object' ? JSON.stringify(value) : String(value)
export const moneyText = (value: string, optional = false): string | null => {
  if (optional && value === '') return null
  if (!/^\d+(\.\d{1,12})?$/.test(value) || value.length > 50) throw new Error('Enter a nonnegative decimal amount (up to 12 decimal places).')
  return value
}
export const integer = (value: string, min = 1, max = 1000000) => {
  if (!/^\d+$/.test(value)) throw new Error('Enter a whole number.')
  const n = Number(value)
  if (!Number.isSafeInteger(n) || n < min || n > max) throw new Error(`Enter a whole number from ${min} to ${max}.`)
  return n
}

export function watchPlatformJob(refresh: () => void, cancel: () => void, interval = 10000) {
  const tick = () => { if (document.visibilityState === 'visible') refresh() }
  const visibility = () => { if (document.visibilityState === 'visible') refresh(); else cancel() }
  const initial = setTimeout(tick, 0), timer = setInterval(tick, interval)
  document.addEventListener('visibilitychange', visibility)
  return () => { clearTimeout(initial); clearInterval(timer); cancel(); document.removeEventListener('visibilitychange', visibility) }
}

/** Every state/auth side effect must follow the same owner + generation fence. */
export class PlatformRequests {
  private generation = 0
  private controllers = new Map<string, AbortController>()
  constructor(private base = apiBase(), private expired = () => window.dispatchEvent(new Event('neodesk:session-expired'))) {}
  invalidate() { this.generation++; this.controllers.forEach(c => c.abort()); this.controllers.clear() }
  cancel(channel: string) { this.controllers.get(channel)?.abort(); this.controllers.delete(channel) }
  async request(path: string, method = 'GET', body?: unknown, channel = path): Promise<unknown> {
    this.controllers.get(channel)?.abort()
    const controller = new AbortController(), generation = this.generation
    this.controllers.set(channel, controller)
    const timeout = setTimeout(() => controller.abort(), 120000)
    const current = () => generation === this.generation && this.controllers.get(channel) === controller && !controller.signal.aborted
    try {
      const response = await fetch(`${this.base}/api/options-platform${path}`, { method, credentials: 'include', headers: { 'Content-Type': 'application/json', 'X-NeoDesk': '1' }, body: body === undefined ? undefined : JSON.stringify(body), signal: controller.signal })
      const data = await response.json()
      if (!current()) throw new DOMException('Superseded request', 'AbortError')
      if (!response.ok) {
        if (response.status === 401) { this.invalidate(); this.expired() }
        if (response.status === 409) throw new Error('Conflict: draft retained. Reload the current server record before retrying.')
        throw new Error(typeof data.detail === 'string' ? data.detail : `Request failed (${response.status}): ${JSON.stringify(data.detail ?? 'Unavailable')}`)
      }
      return data
    } finally { clearTimeout(timeout) }
  }
}
