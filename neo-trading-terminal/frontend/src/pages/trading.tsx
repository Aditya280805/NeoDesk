import { useEffect, useState } from 'react'
import { useRouter } from 'next/router'
import InstrumentPicker from '@/components/InstrumentPicker'
import TradeTicket from '@/components/TradeTicket'
import { api, failure, Instrument, money } from '@/lib/api'
import { useQuotes } from '@/lib/useQuotes'
import { useTerminal } from '@/components/Layout'
import { useMarketStore } from '@/stores/marketStore'
import BrokerPortfolio from '@/components/BrokerPortfolio'

type Order = {
  id: string
  symbol: string
  side: string
  quantity: number
  status: string
  fill_price: number | null
  limit_price: number | null
}

type Account = {
  initial: number
  cash: number
  available: number
  reserved: number
  futures_margin: number
  realized: number
  equity: number | null
  source: string
  valuation_error: string | null
  positions: {
    instrument_id: string
    symbol: string
    quantity: number
    average_price: number
    ltp: number | null
    pnl: number | null
    kind: string
  }[]
  orders: Order[]
}

export default function Trading() {
  const mode = useMarketStore(s => s.tradingMode)
  return mode === 'LIVE' ? <BrokerPortfolio /> : <PaperTrading />
}

function PaperTrading() {
  const router = useRouter()
  const { status } = useTerminal()
  const { tradingMode } = useMarketStore()
  const endpoint = tradingMode === 'LIVE' ? '/live' : '/paper'

  const [account, setAccount] = useState<Account | null>(null)
  const [instrument, setInstrument] = useState<Instrument | null>(null)
  const [ticketSide, setTicketSide] = useState<'BUY' | 'SELL'>('BUY')
  const [ticketQty, setTicketQty] = useState<number | undefined>(undefined)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const { quotes, error: quoteError } = useQuotes(instrument ? [instrument.id] : [])

  async function refresh() {
    try {
      setAccount(await api<Account>(endpoint))
      setError('')
    } catch (e) {
      setError(failure(e))
    }
  }

  useEffect(() => {
    let active = true, running = false
    async function load() {
      if (running) return
      running = true
      try {
        const r = await api<Account>(endpoint)
        if (active) setAccount(r)
      } catch (e) {
        if (active) setError(failure(e))
      } finally {
        running = false
      }
    }
    void load()
    const timer = setInterval(load, 5000)
    return () => {
      active = false
      clearInterval(timer)
    }
  }, [status?.market_data_source, endpoint])

  useEffect(() => {
    if (typeof router.query.instrument !== 'string') return
    let active = true
    api<Instrument>(`/instruments/${encodeURIComponent(router.query.instrument)}`)
      .then(i => {
        if (active) {
          setTicketSide('BUY')
          setTicketQty(undefined)
          setInstrument(i)
        }
      })
      .catch(e => {
        if (active) setError(failure(e))
      })
    return () => {
      active = false
    }
  }, [router.query.instrument])

  async function reset() {
    if (tradingMode === 'LIVE') return
    const confirmation = window.prompt('This removes paper orders and positions. Type RESET PAPER ACCOUNT to confirm.')
    if (!confirmation) return
    try {
      setAccount(await api<Account>('/paper/reset', 'POST', { confirmation }))
      setNotice('Paper account reset.')
      setError('')
    } catch (e) {
      setError(failure(e))
    }
  }

  async function selectPosition(id: string) {
    try {
      setTicketSide('BUY')
      setTicketQty(undefined)
      setInstrument(await api<Instrument>(`/instruments/${encodeURIComponent(id)}`))
    } catch (e) {
      setError(failure(e))
    }
  }

  async function squareOff(p: { instrument_id: string; quantity: number }) {
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

  const unrealizedPnl = account?.positions.reduce((sum, p) => (p.pnl != null ? sum + p.pnl : sum), 0) ?? 0
  const realizedPnl = account?.realized ?? 0

  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">{tradingMode === 'LIVE' ? 'LIVE PORTFOLIO' : 'YOUR PRACTICE PORTFOLIO'}</p>
          <h1>
            {tradingMode === 'LIVE' ? 'Live trading' : 'Paper trading'}
            <span className="accent">.</span>
          </h1>
          <p>
            {tradingMode === 'LIVE'
              ? 'Real money execution.'
              : `${money(account?.initial ?? 100000)} initial capital · stocks, long options and futures.`}
          </p>
        </div>
        <span className={`badge ${tradingMode === 'LIVE' ? 'amber' : ''}`}>
          {tradingMode === 'LIVE' ? 'LIVE MARKET EXECUTION' : 'SIMULATED EXECUTION'}
        </span>
      </div>

      <div className="metrics workstation-metrics">
        <div className="metric">
          <span className="metric-label">Account equity</span>
          <strong>{account?.equity == null ? '—' : money(account.equity)}</strong>
        </div>
        <div className="metric">
          <span className="metric-label">Available cash</span>
          <strong>{account?.available == null ? '—' : money(account.available)}</strong>
        </div>
        <div className="metric pnl-card">
          <div className="metric-header">
            <span className="metric-label">Realized P&L</span>
            <span className={`pnl-badge ${realizedPnl >= 0 ? 'positive' : 'negative'}`}>
              {realizedPnl >= 0 ? '+' : ''}{money(realizedPnl)}
            </span>
          </div>
          <strong className={realizedPnl >= 0 ? 'positive' : 'negative'}>
            {money(realizedPnl)}
          </strong>
        </div>
        <div className="metric pnl-card">
          <div className="metric-header">
            <span className="metric-label">Unrealized P&L</span>
            <span className={`pnl-badge ${unrealizedPnl >= 0 ? 'positive' : 'negative'}`}>
              {unrealizedPnl >= 0 ? '+' : ''}{money(unrealizedPnl)}
            </span>
          </div>
          <strong className={unrealizedPnl >= 0 ? 'positive' : 'negative'}>
            {money(unrealizedPnl)}
          </strong>
        </div>
      </div>

      {(error || quoteError || account?.valuation_error) && (
        <p className="error">{error || quoteError || account?.valuation_error}</p>
      )}
      {notice && <p className="success">{notice}</p>}

      <div className="trading-layout">
        <div>
          <section className="panel">
            <div className="section-heading padded">
              <h2>Positions</h2>
              <span className="muted">{account?.source} prices</span>
            </div>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>INSTRUMENT</th>
                    <th>QTY</th>
                    <th>AVERAGE</th>
                    <th>LTP</th>
                    <th>P&L</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {account?.positions.map(p => (
                    <tr key={p.instrument_id}>
                      <td>
                        <strong>{p.symbol}</strong>
                        <small className="instrument-name">
                          {p.kind === 'FUTURE'
                            ? p.quantity < 0
                              ? 'Short future'
                              : 'Long future'
                            : 'Cash / long option'}
                        </small>
                      </td>
                      <td className="numeric">{p.quantity}</td>
                      <td className="numeric">{money(p.average_price)}</td>
                      <td className="numeric">{p.ltp == null ? '—' : money(p.ltp)}</td>
                      <td className={`numeric ${(p.pnl ?? 0) >= 0 ? 'positive' : 'negative'}`}>
                        {p.pnl == null ? '—' : money(p.pnl)}
                      </td>
                      <td>
                        <div className="table-actions">
                          <button type="button" onClick={() => void selectPosition(p.instrument_id)}>
                            Trade
                          </button>
                          <button
                            type="button"
                            className="square-off-btn"
                            onClick={() => void squareOff(p)}
                          >
                            Square off
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {!account?.positions.length && (
              <div className="empty-state">
                {tradingMode === 'LIVE' ? 'No live positions.' : 'Your first paper trade starts here.'}
                <small>Choose a stock or index contract to begin.</small>
              </div>
            )}
          </section>

          <section className="panel spaced">
            <div className="section-heading padded">
              <h2>Order book</h2>
              {tradingMode === 'PAPER' && <button onClick={reset}>Reset account</button>}
            </div>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>INSTRUMENT</th>
                    <th>SIDE / QTY</th>
                    <th>PRICE</th>
                    <th>STATUS</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {account?.orders.map(o => (
                    <tr key={o.id}>
                      <td>
                        <strong>{o.symbol}</strong>
                        <small className="instrument-name">{o.id}</small>
                      </td>
                      <td>
                        <span className={o.side === 'BUY' ? 'positive' : 'negative'}>{o.side}</span> · {o.quantity}
                      </td>
                      <td className="numeric">
                        {o.fill_price != null || o.limit_price != null
                          ? money((o.fill_price ?? o.limit_price ?? 0) / 100)
                          : '—'}
                      </td>
                      <td>
                        <span className="tag">{o.status}</span>
                      </td>
                      <td>
                        {o.status === 'OPEN' && (
                          <button
                            onClick={async () => {
                              try {
                                await api(`${endpoint}/orders/${o.id}`, 'DELETE')
                                await refresh()
                              } catch (e) {
                                setError(failure(e))
                              }
                            }}
                          >
                            Cancel
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {!account?.orders.length && <div className="empty-state">No orders yet.</div>}
          </section>
          <p className="fine-print">
            Futures collateral: {money(account?.futures_margin ?? 0)}. The simulator reserves 20% of entry notional. Unrealized gains do not increase available cash. Losses can exceed collateral; daily settlement and forced liquidation are not simulated. Close derivatives before expiry.
          </p>
        </div>

        <div className="selection-column">
          <section className="panel padded">
            <h2>Find an instrument</h2>
            <InstrumentPicker
              onSelect={inst => {
                setTicketSide('BUY')
                setTicketQty(undefined)
                setInstrument(inst)
              }}
            />
          </section>
          {instrument && (
            <div className="spaced">
              <TradeTicket
                key={`${tradingMode}-${instrument.id}-${ticketSide}-${ticketQty}`}
                instrument={instrument}
                quote={quotes[instrument.id]}
                initialSide={ticketSide}
                initialQuantity={ticketQty}
                onFilled={refresh}
              />
            </div>
          )}
        </div>
      </div>
    </>
  )
}
