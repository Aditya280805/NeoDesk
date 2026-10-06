import { useRouter } from 'next/router'
import { useEffect, useState } from 'react'
import dynamic from 'next/dynamic'
import Link from 'next/link'
import { ArrowLeft, ArrowUpRight } from 'lucide-react'
import { api, failure, Instrument, money, Quote } from '@/lib/api'
import { useTerminal } from '@/components/Layout'
import { History } from '@/components/PriceChart'

const PriceChart = dynamic(() => import('@/components/PriceChart'), { ssr: false })

const RANGES = [
  { label: '1D', interval: '1min', days: 1 },
  { label: '5D', interval: '5min', days: 5 },
  { label: '30D', interval: '60min', days: 30 },
  { label: '1Y', interval: 'D', days: 365 },
  { label: '5Y', interval: 'D', days: 1825 },
]

export default function InstrumentDashboard() {
  const router = useRouter()
  const { status } = useTerminal()
  const id = typeof router.query.id === 'string' ? router.query.id : ''
  
  const [instrument, setInstrument] = useState<Instrument | null>(null)
  const [quote, setQuote] = useState<Quote | null>(null)
  const [history, setHistory] = useState<History | null>(null)
  const [range, setRange] = useState(RANGES[3]) // Default 1Y
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!id) return
    let active = true
    api<Instrument>(`/instruments/${encodeURIComponent(id)}`)
      .then(r => { if (active) setInstrument(r) })
      .catch(e => { if (active) setError(failure(e)) })
    return () => { active = false }
  }, [id])

  useEffect(() => {
    if (!id) return
    let active = true
    const updateQuote = async () => {
      try {
        const res = await api<Quote[]>('/market/quotes', 'POST', { ids: [id] })
        if (active && res.length > 0) setQuote(res[0])
      } catch (e) {
        // fail silently for live quotes
      }
    }
    updateQuote()
    const timer = setInterval(updateQuote, 5000)
    return () => { active = false; clearInterval(timer) }
  }, [id, status?.market_data_source])

  useEffect(() => {
    if (!id) return
    let active = true
    let running = false
    const loadHistory = async () => {
      if (running) return
      running = true; setBusy(true)
      try {
        const r = await api<History>(`/market/history?instrument_id=${encodeURIComponent(id)}&interval=${range.interval}&days=${range.days}`)
        if (active) { setHistory(r); setError('') }
      } catch (e) {
        if (active) { setHistory(null); setError(failure(e)) }
      } finally {
        running = false; if (active) setBusy(false)
      }
    }
    loadHistory()
    const timer = setInterval(loadHistory, 60000)
    return () => { active = false; clearInterval(timer) }
  }, [id, range, status?.market_data_source])

  if (!id) return null

  const isPositive = (quote?.change_pct ?? 0) >= 0

  return (
    <>
      <div className="page-heading">
        <div>
          <Link href="/stocks" className="text-link" style={{ display: 'flex', alignItems: 'center', gap: '4px', marginBottom: '12px' }}>
            <ArrowLeft size={14} /> Back to Discover
          </Link>
          <p className="eyebrow">INSTRUMENT DASHBOARD</p>
          <h1>{instrument?.symbol || id}<span className="accent">.</span></h1>
          <p>{instrument?.name || 'Loading details...'}</p>
        </div>
        <Link className="button primary" href={`/paper/?instrument=${encodeURIComponent(id)}`}>
          Trade on Paper <ArrowUpRight size={16} />
        </Link>
      </div>

      {error && <p className="error" role="alert" style={{ marginBottom: '20px' }}>{error}</p>}

      <div className="instrument-dashboard">
        <section className="main-content">
          <div className="dashboard-header">
            <div>
              <h1>{instrument?.symbol || '---'}</h1>
              <span className="tag" style={{ marginTop: '8px', display: 'inline-block' }}>{instrument?.exchange.toUpperCase()}</span>
            </div>
            <div className="price-block">
              <strong>{money(quote?.ltp)}</strong>
              <span className={isPositive ? 'positive' : 'negative'}>
                {isPositive ? '+' : ''}{quote?.change_pct?.toFixed(2) ?? '---'}%
              </span>
            </div>
          </div>
          <div className="chart-container">
            <div className="range-selector">
              {RANGES.map(r => (
                <button
                  key={r.label}
                  className={range.label === r.label ? 'active' : ''}
                  onClick={() => setRange(r)}
                  disabled={busy}
                >
                  {r.label}
                </button>
              ))}
              {busy && <span className="muted" style={{ fontSize: '11px', alignSelf: 'center', marginLeft: 'auto' }}>Loading...</span>}
            </div>
            {history ? <PriceChart data={history} instrumentId={id} /> : <div style={{ height: '440px', display: 'grid', placeItems: 'center' }} className="muted">No chart data available.</div>}
            <p className={history?.partial ? 'error' : 'fine-print'} style={{ padding: '0 10px' }}>
              {history?.note}
            </p>
          </div>
        </section>

        <section className="data-panel">
          <div className="data-panel-card">
            <h3>Technical Indicators</h3>
            <div className="data-grid">
              <div className="data-row"><span>RSI (14)</span><span>{history?.indicators.rsi14.at(-1)?.toFixed(2) ?? 'N/A'}</span></div>
              <div className="data-row"><span>SMA 20</span><span>{history?.indicators.sma20.at(-1)?.toFixed(2) ?? 'N/A'}</span></div>
              <div className="data-row"><span>SMA 50</span><span>{history?.indicators.sma50.at(-1)?.toFixed(2) ?? 'N/A'}</span></div>
              <div className="data-row"><span>SMA 200</span><span>{history?.indicators.sma200.at(-1)?.toFixed(2) ?? 'N/A'}</span></div>
            </div>
          </div>

          <div className="data-panel-card">
            <h3>Instrument Info</h3>
            <div className="data-grid">
              <div className="data-row"><span>Exchange</span><span>{instrument?.exchange.toUpperCase() ?? 'N/A'}</span></div>
              <div className="data-row"><span>Type</span><span>{instrument?.kind ?? 'N/A'}</span></div>
              <div className="data-row"><span>Lot Size</span><span>{instrument?.lot_size ?? 'N/A'}</span></div>
              <div className="data-row"><span>Tick Size</span><span>{instrument?.tick_size ?? 'N/A'}</span></div>
              {instrument?.kind === 'OPTION' && (
                <>
                  <div className="data-row"><span>Strike</span><span>{instrument.strike}</span></div>
                  <div className="data-row"><span>Expiry</span><span>{instrument.expiry}</span></div>
                </>
              )}
            </div>
          </div>
          
          <div className="data-panel-card">
            <h3>Fundamentals</h3>
            <div className="data-grid">
              <div className="data-row"><span>P/E Ratio</span><span className="muted">N/A</span></div>
              <div className="data-row"><span>Market Cap</span><span className="muted">N/A</span></div>
              <div className="data-row"><span>52W High</span><span className="muted">N/A</span></div>
              <div className="data-row"><span>52W Low</span><span className="muted">N/A</span></div>
            </div>
            <p className="fine-print" style={{ marginTop: '16px' }}>Fundamental metrics are not supported by the current broker API capabilities.</p>
          </div>
        </section>
      </div>
    </>
  )
}
