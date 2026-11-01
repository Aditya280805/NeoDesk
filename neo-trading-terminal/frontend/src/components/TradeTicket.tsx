import { FormEvent, useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { api, failure, Instrument, money, Quote } from '@/lib/api'
import { useTerminal } from './Layout'
import { useMarketStore } from '@/stores/marketStore'

type Balance = { available: number; source: string; futures_margin_rate: number }

export default function TradeTicket({
  instrument,
  quote,
  onFilled,
  initialSide = 'BUY',
  initialQuantity
}: {
  instrument: Instrument
  quote?: Quote
  onFilled?: () => void
  initialSide?: 'BUY' | 'SELL'
  initialQuantity?: number
}) {
  const { status } = useTerminal()
  const { tradingMode } = useMarketStore()
  const endpoint = tradingMode === 'LIVE' ? '/live' : '/paper'

  const derivative = ['OPTION', 'FUTURE'].includes(instrument.kind)
  const future = instrument.kind === 'FUTURE'
  const ltp = quote?.ltp

  const defaultAmount = initialQuantity != null
    ? (derivative && instrument.lot_size && initialQuantity >= instrument.lot_size
        ? Math.max(1, Math.round(initialQuantity / instrument.lot_size))
        : Math.max(1, Math.round(initialQuantity)))
    : 1

  const [side, setSide] = useState<'BUY' | 'SELL'>(initialSide)
  const [amount, setAmount] = useState<number>(defaultAmount)
  const [type, setType] = useState('MARKET')
  const [price, setPrice] = useState('')
  const [product, setProduct] = useState<'MIS' | 'CNC' | 'NRML'>(derivative ? 'NRML' : 'CNC')
  const [account, setAccount] = useState<Balance | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const retry = useRef<{ key: string; id: string } | null>(null)
  const [review, setReview] = useState<string | null>(null)

  const quantity = amount * (derivative ? instrument.lot_size : 1)
  const value = quantity * (type === 'LIMIT' ? Number(price) : ltp ?? 0)
  const supported = ['EQUITY', 'ETF', 'OPTION', 'FUTURE'].includes(instrument.kind)

  useEffect(() => {
    if (initialSide) setSide(initialSide)
  }, [initialSide])

  useEffect(() => {
    if (initialQuantity != null) {
      const calculated = derivative && instrument.lot_size && initialQuantity >= instrument.lot_size
        ? Math.max(1, Math.round(initialQuantity / instrument.lot_size))
        : Math.max(1, Math.round(initialQuantity))
      setAmount(calculated)
    }
  }, [initialQuantity, derivative, instrument.lot_size])

  useEffect(() => {
    setProduct(derivative ? 'NRML' : 'CNC')
  }, [derivative])

  useEffect(() => {
    let active = true
    const load = async () => {
      try {
        const a = await api<Balance>(endpoint)
        if (active) setAccount(a)
      } catch (e) {
        if (active) setError(failure(e))
      }
    }
    void load()
    const timer = setInterval(load, 10000)
    return () => {
      active = false
      clearInterval(timer)
    }
  }, [status?.market_data_source, endpoint])

  async function submit(e: FormEvent) {
    e.preventDefault()
    setError('')
    setNotice('')
    const payload = {
      instrument_id: instrument.id,
      side,
      quantity,
      order_type: type,
      limit_price: type === 'LIMIT' ? Number(price) : null,
      ...(tradingMode === 'LIVE' ? { product } : {})
    }
    const reviewKey = JSON.stringify(payload)
    const key = endpoint + reviewKey
    if (tradingMode === 'LIVE' && review !== reviewKey) {
      setReview(reviewKey)
      return
    }
    setBusy(true)
    if (retry.current?.key !== key) retry.current = { key, id: crypto.randomUUID() }
    try {
      const order = await api<{ id: string; status: string }>(`${endpoint}/orders`, 'POST', {
        ...payload,
        request_id: retry.current.id
      })
      retry.current = null
      setReview(null)
      setNotice(`${order.status} · ${order.id}`)
      onFilled?.()
      try {
        setAccount(await api<Balance>(endpoint))
      } catch {
        setNotice(`${order.status} · ${order.id}. Balance refresh unavailable; check your order book before placing another order.`)
      }
    } catch (e) {
      setError(failure(e))
    } finally {
      setBusy(false)
    }
  }

  const reviewPayload = JSON.stringify({
    instrument_id: instrument.id,
    side,
    quantity,
    order_type: type,
    limit_price: type === 'LIMIT' ? Number(price) : null,
    ...(tradingMode === 'LIVE' ? { product } : {})
  })

  return (
    <section className="panel padded ticket">
      <div className="section-heading">
        <h2>Order ticket</h2>
        <span className={`badge ${tradingMode === 'LIVE' ? 'amber' : ''}`}>{tradingMode}</span>
      </div>
      <div className="ticket-symbol">
        <strong>{instrument.symbol}</strong>
        <span>{money(ltp)}</span>
        <small>
          {instrument.exchange.toUpperCase()} · {instrument.kind}
          {derivative ? ` · ${instrument.lot_size} units / lot` : ''}
        </small>
      </div>
      {derivative && (
        <p className="contract-description">
          Expiry {instrument.expiry || 'unavailable'}
          {instrument.kind === 'OPTION' ? ` · ${instrument.strike} ${instrument.option_type}` : ''}
        </p>
      )}
      <form onSubmit={submit}>
        <div className="side-toggle">
          <button
            type="button"
            className={side === 'BUY' ? 'buy selected' : ''}
            onClick={() => setSide('BUY')}
          >
            {future ? 'Buy / close short' : 'Buy'}
          </button>
          <button
            type="button"
            className={side === 'SELL' ? 'sell selected' : ''}
            onClick={() => setSide('SELL')}
          >
            {future ? 'Sell / close long' : 'Sell holdings'}
          </button>
        </div>

        <div className="product-tabs" role="tablist" aria-label="Product selector">
          {(['MIS', 'CNC', 'NRML'] as const).map((p) => {
            const disabled = derivative ? p === 'CNC' : p === 'NRML'
            return (
              <button
                key={p}
                type="button"
                role="tab"
                aria-selected={product === p}
                disabled={disabled}
                className={`product-tab ${product === p ? 'active' : ''} ${disabled ? 'disabled' : ''}`}
                onClick={() => !disabled && setProduct(p)}
              >
                <span className="product-tab-name">{p}</span>
                <small className="product-tab-label">
                  {p === 'MIS' ? 'Intraday' : p === 'CNC' ? 'Delivery' : 'Normal (F&O)'}
                </small>
              </button>
            )
          })}
        </div>

        <div className="form-row">
          <label>
            <div className="field-label-header">
              <span>{derivative ? 'Lots' : 'Quantity'}</span>
              <div className="stepper-buttons">
                <button
                  type="button"
                  className="stepper-btn"
                  onClick={() => setAmount((a) => Math.max(1, (a || 0) + 1))}
                  title="Add 1"
                >
                  +1
                </button>
                <button
                  type="button"
                  className="stepper-btn"
                  onClick={() => setAmount((a) => Math.max(1, (a || 0) + 5))}
                  title="Add 5"
                >
                  +5
                </button>
              </div>
            </div>
            <input
              aria-label={derivative ? 'Lots' : 'Quantity'}
              type="number"
              min="1"
              step="1"
              max={Math.floor(10000 / (derivative ? instrument.lot_size : 1))}
              required
              value={amount}
              onChange={(e) => setAmount(Number(e.target.value))}
            />
          </label>
          <label>
            Order type
            <select value={type} onChange={(e) => setType(e.target.value)}>
              <option>MARKET</option>
              {(!future || tradingMode === 'LIVE') && <option>LIMIT</option>}
            </select>
          </label>
        </div>

        {type === 'LIMIT' && (
          <label>
            Limit price
            <input
              required
              type="number"
              min={instrument.tick_size}
              step={instrument.tick_size}
              value={price}
              onChange={(e) => setPrice(e.target.value)}
            />
          </label>
        )}

        {derivative && (
          <p className="fine-print">
            {amount} lots × {instrument.lot_size} = {quantity} units
          </p>
        )}
        <div className="ticket-estimate">
          <span>{future ? 'Contract notional' : 'Estimated value'}</span>
          <strong>{money(value)}</strong>
        </div>
        {future && tradingMode === 'PAPER' && (
          <div className="ticket-estimate">
            <span>Opening margin · 20%</span>
            <strong>{money(value * 0.2)}</strong>
          </div>
        )}
        <div className="ticket-estimate">
          <span>Available {tradingMode === 'LIVE' ? 'live' : 'paper'} cash</span>
          <strong>{money(account?.available)}</strong>
        </div>

        {tradingMode === 'LIVE' && review === reviewPayload && (
          <p className="auth-message" role="status">
            Review: {side} {quantity} units of {instrument.symbol}, {type}
            {type === 'LIMIT' ? ` at ${money(Number(price))}` : ''}. Product: {product}. Confirm below to send this order to Kotak.
          </p>
        )}

        <button
          className={`primary execution-btn ${side === 'SELL' ? 'sell-button' : 'buy-button'}`}
          disabled={
            busy ||
            !ltp ||
            !supported ||
            (tradingMode === 'LIVE' &&
              (!status?.broker_authenticated || !status.live_trading_enabled || status.orders_stopped))
          }
        >
          {busy ? (
            <>
              <span className="spinner"></span> Submitting…
            </>
          ) : tradingMode === 'LIVE' ? (
            review === reviewPayload ? (
              'Confirm live order'
            ) : (
              'Review live order'
            )
          ) : (
            `${side === 'BUY' ? 'Buy' : 'Sell'} paper ${future ? 'futures' : instrument.kind === 'OPTION' ? 'option' : 'shares'}`
          )}
        </button>

        {tradingMode === 'LIVE' && status?.orders_stopped && (
          <p className="error" role="status">
            New orders are stopped. Use Resume orders in the top bar when ready.
          </p>
        )}
        {tradingMode === 'LIVE' && !status?.live_trading_enabled && (
          <p className="fine-print">Live order execution is disabled on this server.</p>
        )}
      </form>

      {!supported && (
        <p className="error">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="10"></circle>
            <line x1="12" y1="8" x2="12" y2="12"></line>
            <line x1="12" y1="16" x2="12.01" y2="16"></line>
          </svg>
          Select a tradable stock, ETF or derivative contract.
        </p>
      )}
      {!ltp && (
        <p className="fine-print">Waiting for a usable price. Orders are unavailable until a quote arrives.</p>
      )}
      {error && (
        <div className="error" role="alert">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="10"></circle>
            <line x1="12" y1="8" x2="12" y2="12"></line>
            <line x1="12" y1="16" x2="12.01" y2="16"></line>
          </svg>
          {error}
        </div>
      )}
      {notice && (
        <div className="success" role="status">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M22 11.08V12a10 10 10 0 1 1-5.93-9.14"></path>
            <polyline points="22 4 12 14.01 9 11.01"></polyline>
          </svg>
          {notice}
        </div>
      )}
      {future ? (
        <p className="fine-print">
          {tradingMode === 'LIVE'
            ? 'Kotak Neo handles futures margins and daily settlement.'
            : 'Simulation reserves 20% of entry notional. This is an illustrative paper margin, not Kotak’s margin requirement. Market orders only; no daily settlement, automatic liquidation or expiry settlement. Close before expiry.'}
        </p>
      ) : (
        <p className="fine-print">
          {tradingMode === 'LIVE'
            ? 'Live orders are sent to Kotak Neo via API.'
            : 'Virtual fills use the last available quote, including after market close. No fees or liquidity model. Sell closes owned shares or long options.'}
        </p>
      )}
      <Link className="text-link" href="/trading/">
        View positions & orders →
      </Link>
    </section>
  )
}
