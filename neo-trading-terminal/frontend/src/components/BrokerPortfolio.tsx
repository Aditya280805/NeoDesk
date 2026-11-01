import Link from 'next/link'
import { useEffect, useState } from 'react'
import { RefreshCw, Wallet } from 'lucide-react'
import { api, failure, Instrument, money } from '@/lib/api'
import InstrumentPicker from './InstrumentPicker'
import TradeTicket from './TradeTicket'
import { useQuotes } from '@/lib/useQuotes'

type Position = {
  quality?: string
  instrument_id: string | null
  symbol: string
  exchange: string
  kind: string
  quantity: number | null
  average_price: number | null
  ltp: number | null
  pnl: number | null
  product?: string
}

type Holding = Position & {
  current_value: number | null
  invested: number | null
  sellable_quantity: number | null
}

type Order = {
  quality?: string
  id: string
  symbol: string
  side: 'BUY' | 'SELL' | 'UNKNOWN' | null
  quantity: number | null
  status: string
  fill_price: number | null
  limit_price: number | null
}

type Portfolio = {
  quality?: string
  available: number | null
  reserved: number | null
  holdings_value: number | null
  invested: number | null
  holdings_pnl: number | null
  realized: number | null
  holdings: Holding[]
  positions: Position[]
  orders: Order[]
  synced_at: string
  quality_issues?: Record<string, { code: string; row_id?: string | null; field?: string | null }[]>
  section_errors?: Partial<Record<'holdings' | 'positions' | 'orders' | 'funds', string>>
}

export default function BrokerPortfolio() {
  const [data, setData] = useState<Portfolio | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [tab, setTab] = useState<'holdings' | 'positions' | 'orders'>('holdings')
  const [instrument, setInstrument] = useState<Instrument | null>(null)
  const [ticketSide, setTicketSide] = useState<'BUY' | 'SELL'>('BUY')
  const [ticketQty, setTicketQty] = useState<number | undefined>(undefined)
  const [cancelling, setCancelling] = useState<string | null>(null)

  const { quotes } = useQuotes(instrument ? [instrument.id] : [])

  async function refresh(force = false) {
    setLoading(true)
    try {
      setData(await api<Portfolio>(`/live${force ? '?refresh=true' : ''}`))
      setError('')
    } catch (e) {
      setError(failure(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    let active = true, running = false
    async function load() {
      if (running) return
      running = true
      try {
        const next = await api<Portfolio>('/live')
        if (active) {
          setData(next)
          setError('')
        }
      } catch (e) {
        if (active) setError(failure(e))
      } finally {
        running = false
      }
    }
    void load()
    const timer = setInterval(load, 15000)
    return () => {
      active = false
      clearInterval(timer)
    }
  }, [])

  async function trade(id: string) {
    try {
      setTicketSide('BUY')
      setTicketQty(undefined)
      setInstrument(await api<Instrument>(`/instruments/${encodeURIComponent(id)}`))
    } catch (e) {
      setError(failure(e))
    }
  }

  async function squareOff(p: Position) {
    if (!p.instrument_id || p.quantity == null || p.quantity === 0) return
    try {
      const inst = await api<Instrument>(`/instruments/${encodeURIComponent(p.instrument_id)}`)
      const inverseSide: 'BUY' | 'SELL' = p.quantity > 0 ? 'SELL' : 'BUY'
      const netQty = Math.abs(p.quantity)
      setTicketSide(inverseSide)
      setTicketQty(netQty)
      setInstrument(inst)
    } catch (e) {
      setError(failure(e))
    }
  }

  async function cancel() {
    if (!cancelling) return
    try {
      await api(`/live/orders/${encodeURIComponent(cancelling)}`, 'DELETE')
      setCancelling(null)
      await refresh(true)
    } catch (e) {
      setError(failure(e))
    }
  }

  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">YOUR KOTAK NEO ACCOUNT</p>
          <h1>
            Your portfolio<span className="accent">.</span>
          </h1>
          <p>Your delivery investments, open positions and orders in one place.</p>
        </div>
        <button onClick={() => void refresh(true)} disabled={loading}>
          <RefreshCw size={15} />
          {loading ? 'Syncing…' : 'Refresh portfolio'}
        </button>
      </div>

      <div className="metrics workstation-metrics">
        {[
          ['Holdings value', data?.holdings_value],
          ['Amount invested', data?.invested],
          ['Holdings P&L', data?.holdings_pnl],
          ['Available funds', data?.available]
        ].map(([title, value]) => (
          <div className="metric" key={String(title)}>
            <span className="metric-label">{title}</span>
            <strong className={title === 'Holdings P&L' ? (Number(value) >= 0 ? 'positive' : 'negative') : ''}>
              {money(typeof value === 'number' ? value : null)}
            </strong>
          </div>
        ))}
      </div>

      <p className="portfolio-sync">
        {data
          ? `Last synced ${new Date(data.synced_at).toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata' })} IST · refreshes every 15 seconds`
          : error
          ? 'Portfolio sync failed. Use Refresh to retry.'
          : 'Loading your Kotak portfolio…'}{' '}
        · Margin used {money(data?.reserved)}
      </p>

      {data?.section_errors &&
        Object.entries(data.section_errors).map(([section, message]) => (
          <p className="error" role="alert" key={section}>
            {section[0].toUpperCase() + section.slice(1)} unavailable: {message} Other available sections are shown
            below.
          </p>
        ))}

      {data?.quality && data.quality !== 'complete' && (
        <p role="status">Portfolio data quality: {data.quality}. Missing values remain unavailable.</p>
      )}

      {data?.quality_issues &&
        Object.entries(data.quality_issues).map(
          ([section, issues]) =>
            issues.length > 0 && (
              <p className="error" role="status" key={section}>
                {section} data quality: {issues.map((i) => `${i.code}${i.field ? ` (${i.field})` : ''}`).join(', ')}
              </p>
            )
        )}

      {error && (
        <p className="error" role="alert">
          {error}
          {data ? ' The last successful snapshot is shown below.' : ''}
        </p>
      )}

      <div className="trading-layout">
        <div>
          <section className="panel">
            <div className="portfolio-tabs" role="tablist" aria-label="Portfolio sections">
              {(['holdings', 'positions', 'orders'] as const).map((t) => (
                <button
                  key={t}
                  role="tab"
                  aria-selected={tab === t}
                  className={tab === t ? 'active' : ''}
                  onClick={() => setTab(t)}
                >
                  {t[0].toUpperCase() + t.slice(1)}{' '}
                  <span>{data?.section_errors?.[t] ? '—' : data?.[t].length ?? '—'}</span>
                </button>
              ))}
            </div>

            {!data ? (
              <div className="empty-state">
                <Wallet size={27} />
                {error ? 'Portfolio could not be loaded. Use Refresh to retry.' : 'Syncing your broker account…'}
              </div>
            ) : data.section_errors?.[tab] ? (
              <div className="empty-state">This section could not be retrieved from Kotak. Use Refresh to retry.</div>
            ) : tab === 'orders' ? (
              <>
                <div className="table-scroll">
                  <table>
                    <thead>
                      <tr>
                        <th>INSTRUMENT</th>
                        <th>SIDE / QTY</th>
                        <th>PRICE</th>
                        <th>STATUS</th>
                        <th />
                      </tr>
                    </thead>
                    <tbody>
                      {data.orders.map((o) => (
                        <tr key={o.id}>
                          <td>
                            {o.symbol}
                            <small className="instrument-name">
                              {o.id}
                              {o.quality === 'partial' && ' · Partial data'}
                            </small>
                          </td>
                          <td>
                            {o.side ?? 'UNKNOWN'} · {o.quantity ?? 'Unavailable'}
                          </td>
                          <td>{money(o.fill_price ?? o.limit_price)}</td>
                          <td>
                            <span className="tag">{o.status}</span>
                          </td>
                          <td>
                            {['OPEN', 'PENDING', 'TRIGGER_PENDING'].includes(o.status) && (
                              <button onClick={() => setCancelling(o.id)}>Cancel</button>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {!data.orders.length && <div className="empty-state">No orders returned by Kotak.</div>}
              </>
            ) : (
              <>
                <div className="table-scroll">
                  <table>
                    <thead>
                      <tr>
                        <th>INSTRUMENT</th>
                        <th>QTY</th>
                        <th>AVG. COST</th>
                        <th>{tab === 'holdings' ? 'VALUE' : 'LTP'}</th>
                        <th>P&L</th>
                        <th />
                      </tr>
                    </thead>
                    <tbody>
                      {(tab === 'holdings' ? data.holdings : data.positions).map((p, i) => (
                        <tr key={`${p.instrument_id}-${p.symbol}-${p.product ?? ''}-${i}`}>
                          <td>
                            {p.instrument_id ? (
                              <Link
                                className="symbol-link"
                                href={`/instrument/?instrument=${encodeURIComponent(p.instrument_id)}`}
                              >
                                {p.symbol}
                              </Link>
                            ) : (
                              p.symbol
                            )}
                            <small className="instrument-name">
                              {p.exchange?.toUpperCase() ?? 'Exchange unavailable'} {p.product ?? ''}
                              {p.quality === 'partial' && ' · Partial data'}
                            </small>
                          </td>
                          <td>{p.quantity ?? 'Unavailable'}</td>
                          <td>{money(p.average_price)}</td>
                          <td>{money(tab === 'holdings' ? (p as Holding).current_value : p.ltp)}</td>
                          <td className={p.pnl === null ? '' : p.pnl >= 0 ? 'positive' : 'negative'}>
                            {money(p.pnl)}
                          </td>
                          <td>
                            {p.instrument_id ? (
                              <div className="table-actions">
                                <button type="button" onClick={() => void trade(p.instrument_id!)}>
                                  Trade
                                </button>
                                {tab === 'positions' && p.quantity != null && p.quantity !== 0 && (
                                  <button
                                    type="button"
                                    className="square-off-btn"
                                    onClick={() => void squareOff(p)}
                                  >
                                    Square off
                                  </button>
                                )}
                              </div>
                            ) : (
                              <span className="muted">Catalogue match pending</span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {!(tab === 'holdings' ? data.holdings : data.positions).length && (
                  <div className="empty-state">
                    {tab === 'holdings'
                      ? 'No delivery holdings were returned by Kotak.'
                      : 'No open positions were returned by Kotak.'}
                  </div>
                )}
              </>
            )}
          </section>
          <p className="fine-print">
            Holdings values are supplied by Kotak. Available funds are shown separately from investments. Unavailable
            values appear as —. Positions can overlap delivery holdings and are not added to the holdings total.
          </p>

          {cancelling && (
            <section className="panel padded spaced" role="alertdialog" aria-label="Confirm cancellation">
              <h2>Cancel order {cancelling}?</h2>
              <p>This requests cancellation in your Kotak account.</p>
              <div className="button-row">
                <button onClick={() => setCancelling(null)}>Keep order</button>
                <button className="danger" onClick={() => void cancel()}>
                  Confirm cancellation
                </button>
              </div>
            </section>
          )}
        </div>

        <div className="selection-column">
          <section className="panel padded">
            <h2>Find a stock or contract</h2>
            <InstrumentPicker
              onSelect={(inst) => {
                setTicketSide('BUY')
                setTicketQty(undefined)
                setInstrument(inst)
              }}
            />
            <p className="fine-print">Search stocks or an exact futures/options contract.</p>
          </section>
          {instrument ? (
            <div className="spaced">
              <TradeTicket
                key={`${instrument.id}-${ticketSide}-${ticketQty}`}
                instrument={instrument}
                quote={quotes[instrument.id]}
                initialSide={ticketSide}
                initialQuantity={ticketQty}
                onFilled={() => void refresh(true)}
              />
            </div>
          ) : (
            <section className="panel padded spaced">
              <h2>Explore the market</h2>
              <p>Choose an investment or contract to open its order ticket.</p>
              <Link className="text-link" href="/stocks/">
                Browse stocks →
              </Link>
              <br />
              <Link className="text-link" href="/indices/">
                Explore index futures & options →
              </Link>
            </section>
          )}
        </div>
      </div>
    </>
  )
}
