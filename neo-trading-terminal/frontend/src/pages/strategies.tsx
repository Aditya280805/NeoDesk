import { FormEvent, useState, useEffect } from 'react'
import InstrumentPicker from '@/components/InstrumentPicker'
import { api, failure, Instrument, money } from '@/lib/api'
import { useMarketStore } from '@/stores/marketStore'

type Result = {
  source: string; instrument: string; initial: number; ending_equity: number;
  return_pct: number; max_drawdown_pct: number; open_quantity: number;
  model: string; note: string; trades: { time: number; side: string; quantity: number; price: number }[]
}

type ActiveStrategy = {
  id: string; instrument_id: string; token: string;
  fast: number; slow: number; initial: number; mode: string;
  cash: number; held: number; status: string;
  pnl?: number; trades?: number;
}

export default function Strategies() {
  const [instrument, setInstrument] = useState<Instrument | null>(null)
  const [result, setResult] = useState<Result | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [activeStrategies, setActiveStrategies] = useState<ActiveStrategy[]>([])
  const { tradingMode, signals, riskAlerts } = useMarketStore()

  async function fetchActive() {
    try {
      setActiveStrategies(await api<ActiveStrategy[]>('/strategies/active'))
    } catch(e) {
      // ignore silently for background refresh
    }
  }

  useEffect(() => {
    let mounted = true;
    async function load() {
      try {
        const data = await api<ActiveStrategy[]>('/strategies/active');
        if (mounted) setActiveStrategies(data);
      } catch(e) {}
    }
    void load();
    const interval = setInterval(load, 5000);
    return () => { mounted = false; clearInterval(interval); };
  }, []);

  async function run(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    if (!instrument) return
    const f = new FormData(e.currentTarget)
    setBusy(true)
    setResult(null)
    try {
      setResult(await api<Result>('/strategies/backtest', 'POST', {
        instrument_id: instrument.id,
        fast: Number(f.get('fast')),
        slow: Number(f.get('slow')),
        initial: Number(f.get('initial')),
        fee_bps: Number(f.get('fee')),
        slippage_bps: Number(f.get('slip'))
      }))
      setError('')
    } catch (e) {
      setError(failure(e))
    } finally {
      setBusy(false)
    }
  }

  async function deploy(e: React.MouseEvent<HTMLButtonElement>) {
    e.preventDefault()
    if (!instrument) return
    const form = e.currentTarget.closest('form')
    if (!form) return
    const f = new FormData(form)
    
    setBusy(true)
    try {
      await api('/strategies/deploy', 'POST', {
        instrument_id: instrument.id,
        fast: Number(f.get('fast')),
        slow: Number(f.get('slow')),
        initial: Number(f.get('initial')),
        mode: tradingMode.toLowerCase()
      })
      setError('')
      await fetchActive()
    } catch (e) {
      setError(failure(e))
    } finally {
      setBusy(false)
    }
  }

  async function stopStrategy(id: string) {
    try {
      await api(`/strategies/${id}`, 'DELETE')
      await fetchActive()
    } catch (e) {
      console.error(e)
    }
  }

  async function pauseStrategy(id: string) {
    try {
      await api(`/strategies/${id}/pause`, 'POST')
      await fetchActive()
    } catch (e) {
      console.error(e)
    }
  }

  async function resumeStrategy(id: string) {
    try {
      await api(`/strategies/${id}/resume`, 'POST')
      await fetchActive()
    } catch (e) {
      console.error(e)
    }
  }

  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">TURN AN IDEA INTO A TEST</p>
          <h1>Strategy lab<span className="accent">.</span></h1>
          <p>Explore a moving-average strategy and deploy it live.</p>
        </div>
        <span className="badge">ALGO ENGINE</span>
      </div>
      
      {activeStrategies.length > 0 && (
        <section className="panel padded" style={{marginBottom: '2rem'}}>
          <h2>Active Deployments</h2>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>INSTRUMENT</th>
                  <th>PARAMETERS</th>
                  <th>MODE</th>
                  <th>CASH</th>
                  <th>HELD</th>
                  <th>P&L</th>
                  <th>TRADES</th>
                  <th>STATUS</th>
                  <th>ACTION</th>
                </tr>
              </thead>
              <tbody>
                {activeStrategies.map(s => (
                  <tr key={s.id}>
                    <td>{s.instrument_id}</td>
                    <td>SMA {s.fast}/{s.slow}</td>
                    <td className={s.mode === 'live' ? 'negative' : 'positive'}>{s.mode.toUpperCase()}</td>
                    <td>{money(s.cash)}</td>
                    <td>{s.held}</td>
                    <td className={s.pnl && s.pnl >= 0 ? 'positive' : 'negative'}>{s.pnl !== undefined ? money(s.pnl) : '-'}</td>
                    <td>{s.trades !== undefined ? s.trades : '-'}</td>
                    <td>{s.status}</td>
                    <td>
                      <div className="button-row" style={{ display: 'flex', gap: '0.5rem' }}>
                        {s.status === 'RUNNING' && (
                          <>
                            <button className="small" onClick={() => pauseStrategy(s.id)}>Pause</button>
                            <button className="small" onClick={() => stopStrategy(s.id)}>Stop</button>
                          </>
                        )}
                        {s.status === 'PAUSED' && (
                          <>
                            <button className="small" onClick={() => resumeStrategy(s.id)}>Resume</button>
                            <button className="small" onClick={() => stopStrategy(s.id)}>Stop</button>
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <div className="two-columns">
        <section className="panel padded">
          <h2>SMA crossover strategy</h2>
          <InstrumentPicker onSelect={setInstrument} />
          <p className="positive">{instrument?.symbol || 'Choose a stock, ETF or index study'}</p>
          <form onSubmit={run}>
            <div className="form-row">
              <label>Fast SMA<input name="fast" type="number" min="2" max="100" defaultValue="20" /></label>
              <label>Slow SMA<input name="slow" type="number" min="3" max="200" defaultValue="50" /></label>
            </div>
            <label>Initial capital (₹)<input name="initial" type="number" min="100" max="10000000" defaultValue="100000" /></label>
            <div className="form-row">
              <label>Fee per side (basis points)<input name="fee" type="number" min="0" max="100" defaultValue="5" /></label>
              <label>Slippage per side (basis points)<input name="slip" type="number" min="0" max="100" defaultValue="5" /></label>
            </div>
            <div className="button-row">
              <button type="submit" disabled={!instrument || busy}>{busy ? 'Running…' : 'Run backtest →'}</button>
              <button type="button" className={tradingMode === 'LIVE' ? 'danger' : 'primary'} onClick={deploy} disabled={!instrument || busy}>
                Deploy to {tradingMode}
              </button>
            </div>
          </form>
          {error && <p className="error">{error}</p>}
        </section>
        
        <section className="panel padded">
          <h2>Live Feed</h2>
          <div className="feed-container" style={{ maxHeight: '400px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
            {riskAlerts.map((alert, i) => (
              <div key={`risk-${i}`} className="alert-item" style={{ padding: '0.5rem', borderLeft: '4px solid #ff4444', backgroundColor: 'rgba(255, 68, 68, 0.1)' }}>
                <strong>RISK ALERT:</strong> {JSON.stringify(alert)}
              </div>
            ))}
            {signals.map((signal, i) => (
              <div key={`sig-${i}`} className="signal-item" style={{ padding: '0.5rem', borderLeft: '4px solid #00C851', backgroundColor: 'rgba(0, 200, 81, 0.1)' }}>
                <strong>SIGNAL:</strong> {JSON.stringify(signal)}
              </div>
            ))}
            {riskAlerts.length === 0 && signals.length === 0 && (
              <p className="fine-print">No live signals or alerts yet.</p>
            )}
          </div>
        </section>
      </div>

      <div className="two-columns">
        <section className="panel padded" style={{ gridColumn: 'span 2' }}>
          <h2>TradingView & your algorithms</h2>
          <p>These charts use TradingView’s open-source Lightweight Charts library with our own Kotak data and indicator calculations.</p>
          <p>Pine Script strategies run on tradingview.com. This embedded chart does not include Pine’s runtime or Strategy Tester.</p>
          <ul className="notes">
            <li>Use Pine Editor and Strategy Tester on TradingView for your existing Pine algorithms.</li>
            <li>This lab supports a configurable SMA crossover using historical candles.</li>
            <li>RSI 14 and SMA 20/50/200 are available on our Charts page.</li>
            <li>Alert webhooks are a future integration; this app does not accept or execute TradingView alerts.</li>
          </ul>
          <a className="text-link" href="https://www.tradingview.com/chart/" target="_blank" rel="noreferrer">Open TradingView ↗</a>
          <p className="fine-print">DMA means a moving average of daily closes here. If you mean displaced moving average, that is a separate indicator.</p>
        </section>
      </div>

      {result && (
        <>
          <div className="section-heading spaced">
            <h2>{result.instrument} · {result.source === 'demo' ? 'SYNTHETIC DATA TEST' : 'KOTAK HISTORICAL TEST'}</h2>
          </div>
          <div className="metrics">
            {[
              ['Ending equity', money(result.ending_equity)],
              ['Return', `${result.return_pct}%`],
              ['Max drawdown', `${result.max_drawdown_pct}%`],
              ['Executions', String(result.trades.length)]
            ].map(([t, v]) => (
              <div className="metric" key={t}>
                <span className="metric-label">{t}</span>
                <strong>{v}</strong>
              </div>
            ))}
          </div>
          <section className="panel padded">
            <p>{result.model}</p>
            <p className="fine-print">{result.note} No out-of-sample validation; short history and survivorship bias limit interpretation. Index studies do not represent an executable index instrument.</p>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>TIME (IST)</th>
                    <th>SIDE</th>
                    <th>QUANTITY</th>
                    <th>FILL PRICE</th>
                  </tr>
                </thead>
                <tbody>
                  {result.trades.map((t, n) => (
                    <tr key={n}>
                      <td>{new Date(t.time * 1000).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' })}</td>
                      <td className={t.side === 'BUY' ? 'positive' : 'negative'}>{t.side}</td>
                      <td>{t.quantity}</td>
                      <td>{money(t.price)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </>
  )
}
