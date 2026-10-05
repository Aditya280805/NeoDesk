import { FormEvent, useState, memo } from 'react'
import Link from 'next/link'
import { api, failure, money } from '@/lib/api'
import { useLiveQuote } from '@/stores/marketStore'

type Leg = {
  instrument: { neoSymbol: string; symbol: string; strikePrice: string; moneyness: string };
  quote: { ltp: string; volume: number };
  openInterest: { current: number; change: number };
}
type Chain = {
  common_data: { unlSymbol: string; expiryDt: string; mktLot: string };
  call: Leg[];
  put: Leg[];
}

const OptionRow = memo(function OptionRow({ s, c, p }: { s: string, c?: Leg, p?: Leg }) {
  const cLtpLive = useLiveQuote(c?.instrument.neoSymbol.split('|')[1] || c?.instrument.neoSymbol)
  const pLtpLive = useLiveQuote(p?.instrument.neoSymbol.split('|')[1] || p?.instrument.neoSymbol)
  const cLtp = cLtpLive ?? (c ? Number(c.quote.ltp) : null)
  const pLtp = pLtpLive ?? (p ? Number(p.quote.ltp) : null)

  const cMoneyness = c?.instrument.moneyness?.toLowerCase() || ''
  const pMoneyness = p?.instrument.moneyness?.toLowerCase() || ''

  return (
    <tr>
      <td className={cMoneyness}>{c?.openInterest.current.toLocaleString('en-IN') ?? '—'}</td>
      <td className={cMoneyness}>{c?.quote.volume?.toLocaleString('en-IN') ?? '—'}</td>
      <td className={`positive ${cMoneyness} ${cLtpLive ? 'live-tick' : ''}`}>{cLtp != null ? money(cLtp) : '—'}</td>
      <td className={cMoneyness}>
        {c && <Link className="text-link" href={`/trading/?instrument=${encodeURIComponent(c.instrument.neoSymbol)}`}>Trade ↗</Link>}
      </td>
      <td className="strike">{s}</td>
      <td className={pMoneyness}>
        {p && <Link className="text-link" href={`/trading/?instrument=${encodeURIComponent(p.instrument.neoSymbol)}`}>Trade ↗</Link>}
      </td>
      <td className={`negative ${pMoneyness} ${pLtpLive ? 'live-tick' : ''}`}>{pLtp != null ? money(pLtp) : '—'}</td>
      <td className={pMoneyness}>{p?.quote.volume?.toLocaleString('en-IN') ?? '—'}</td>
      <td className={pMoneyness}>{p?.openInterest.current.toLocaleString('en-IN') ?? '—'}</td>
    </tr>
  )
})

export default function Options() {
  const [underlying, setUnderlying] = useState('NIFTY')
  const [exchange, setExchange] = useState('nse_fo')
  const [expiry, setExpiry] = useState('')
  const [expiries, setExpiries] = useState<string[]>([])
  const [chain, setChain] = useState<Chain | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function load(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError('')
    setChain(null)
    try {
      const exp = await api<{ expiries: string[] }>(`/market/expiries?underlying=${encodeURIComponent(underlying)}&exchange=${exchange}`)
      setExpiries(exp.expiries)
      const r = await api<Chain>(`/market/chain?underlying=${encodeURIComponent(underlying)}&exchange=${exchange}${expiry ? `&expiry=${expiry}` : ''}`)
      setChain(r)
    } catch (e) {
      setError(failure(e))
    } finally {
      setBusy(false)
    }
  }

  const strikes = Array.from(new Set([...(chain?.call || []), ...(chain?.put || [])].map(l => l.instrument.strikePrice))).sort((a, b) => Number(a) - Number(b))

  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">A VIEW ACROSS THE STRIKES</p>
          <h1>Option chain<span className="accent">.</span></h1>
          <p>Calls, puts, premiums and open interest from Kotak.</p>
        </div>
        <span className="badge">BROKER SNAPSHOT</span>
      </div>
      <section className="panel">
        <form className="toolbar" onSubmit={load}>
          <label>Underlying
            <input value={underlying} onChange={e => { setUnderlying(e.target.value.toUpperCase()); setExpiry(''); setExpiries([]); setChain(null) }} placeholder="NIFTY, BANKNIFTY, RELIANCE" required />
          </label>
          <label>Exchange
            <select value={exchange} onChange={e => { setExchange(e.target.value); setExpiry(''); setExpiries([]); setChain(null) }}>
              <option value="nse_fo">NSE F&O</option>
              <option value="bse_fo">BSE F&O</option>
            </select>
          </label>
          <label>Expiry
            <select value={expiry} onChange={e => setExpiry(e.target.value)}>
              <option value="">Nearest available</option>
              {expiries.map(x => <option key={x}>{x}</option>)}
            </select>
          </label>
          <button className="primary" disabled={busy}>{busy ? 'Loading…' : 'Load chain'}</button>
        </form>
        {error && <p className="error">{error}</p>}
        {chain && (
          <>
            <div className="chain-heading">
              <span>CALLS</span>
              <b>{chain.common_data.unlSymbol} · {chain.common_data.expiryDt} · Lot {chain.common_data.mktLot}</b>
              <span>PUTS</span>
            </div>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>CALL OI</th>
                    <th>VOLUME</th>
                    <th>CALL LTP</th>
                    <th></th>
                    <th className="strike">STRIKE</th>
                    <th></th>
                    <th>PUT LTP</th>
                    <th>VOLUME</th>
                    <th>PUT OI</th>
                  </tr>
                </thead>
                <tbody>
                  {strikes.map(s => {
                    const c = chain.call.find(l => l.instrument.strikePrice === s)
                    const p = chain.put.find(l => l.instrument.strikePrice === s)
                    return <OptionRow key={s} s={s} c={c} p={p} />
                  })}
                </tbody>
              </table>
            </div>
          </>
        )}
        {!chain && !busy && (
          <div className="empty-state">
            Choose an underlying and load its option chain.
            <small>Requires a connected Kotak API key. No sample chain is substituted.</small>
          </div>
        )}
      </section>
    </>
  )
}
