// Neo-trading-terminal API utilities
export function apiBase() {
  if (process.env.NEXT_PUBLIC_API_URL) return process.env.NEXT_PUBLIC_API_URL
  if (typeof window !== 'undefined' && window.location.port === '3000') return `${window.location.protocol}//${window.location.hostname}:8000`
  return ''
}

export function clearLegacyAuthToken(): void {
  if (typeof window === 'undefined') return
  localStorage.removeItem('neodesk_token')
}

export class ApiError extends Error {
  constructor(message: string, public status: number, public code?: string) {
    super(message)
    this.name = 'ApiError'
  }
}

export async function api<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    'X-NeoDesk': '1',
  }
  const response = await fetch(`${apiBase()}/api${path}`, {
    method,
    credentials: 'include',
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: AbortSignal.timeout(120000),
  })
  const data = await response.json().catch(() => {
    throw new Error(`Unexpected server response (${response.status}). Please retry.`)
  })
  if (!response.ok) {
    if(response.status===401&&!path.startsWith('/auth/')&&path!=='/session'&&typeof window!=='undefined')window.dispatchEvent(new Event('neodesk:session-expired'))
    const detail = data?.detail
    const message = typeof detail === 'string' ? detail
      : typeof detail?.message === 'string' ? detail.message : `Request failed (${response.status})`
    throw new ApiError(message, response.status, typeof detail?.code === 'string' ? detail.code : undefined)
  }
  return data as T
}

export type User = {
  id: number
  email: string
  display_name: string
  created_at: string
}

export type AuthResponse = {
  access_token: string
  token_type: string
  user: User
}

export type Instrument = { id:string; symbol:string; name:string; exchange:string; kind:string; underlying:string; lot_size:number; tick_size:number; expiry:string; strike:number; option_type?:string; display_name?:string }
export type Quote = { id:string; symbol:string; ltp:number; change_pct:number; source:string; received_at:string; last_trade_time?:string; volume?:number|null; turnover_estimate?:number|null; ohlc?:{open?:number;high?:number;low?:number;close?:number} }
export type Catalogue = { total:number; updated_at:string|null; counts:{exchange:string;kind:string;count:number}[] }
export type Status = { market_data_source:string; kotak_api_key_configured:boolean; broker_authenticated:boolean; live_trading_enabled:boolean; orders_stopped?:boolean; catalogue:Catalogue; catalogue_sync:{running:boolean;error:string|null}; market_error:string|null }
export const money = (v:number|null|undefined) => v == null ? '—' : new Intl.NumberFormat('en-IN',{style:'currency',currency:'INR',maximumFractionDigits:2}).format(v)
export const failure = (e:unknown) => e instanceof Error ? e.message : 'Request failed. Please try again.'
