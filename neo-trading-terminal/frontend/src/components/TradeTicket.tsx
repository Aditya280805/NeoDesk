import { FormEvent, useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { api, failure, Instrument, money, Quote } from '@/lib/api'
import { useTerminal } from './Layout'
import { useMarketStore } from '@/stores/marketStore'

type Balance={available:number;source:string;futures_margin_rate:number}
export default function TradeTicket({instrument,quote,onFilled,initialSide='BUY'}:{instrument:Instrument;quote?:Quote;onFilled?:()=>void;initialSide?:'BUY'|'SELL'}){
  const {status}=useTerminal()
  const { tradingMode } = useMarketStore()
  const endpoint = tradingMode === 'LIVE' ? '/live' : '/paper'
  const [side,setSide]=useState(initialSide),[amount,setAmount]=useState(1),[type,setType]=useState('MARKET'),[price,setPrice]=useState('')
  const [account,setAccount]=useState<Balance|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState('')
  const retry=useRef<{key:string;id:string}|null>(null)
  const derivative=['OPTION','FUTURE'].includes(instrument.kind),future=instrument.kind==='FUTURE'
  const liveLtp = undefined
  const ltp = quote?.ltp
  const quantity=amount*(derivative?instrument.lot_size:1)
  const value=quantity*(type==='LIMIT'?Number(price):ltp??0)
  const supported=['EQUITY','ETF','OPTION','FUTURE'].includes(instrument.kind)
  useEffect(()=>{let active=true;const load=async()=>{try{const a=await api<Balance>(endpoint);if(active)setAccount(a)}catch(e){if(active)setError(failure(e))}};void load();const timer=setInterval(load,10000);return()=>{active=false;clearInterval(timer)}},[status?.market_data_source, endpoint])
  async function submit(e:FormEvent){
    e.preventDefault();setBusy(true);setError('');setNotice('')
    const payload={instrument_id:instrument.id,side,quantity,order_type:type,limit_price:type==='LIMIT'?Number(price):null}
    const key=JSON.stringify(payload)
    if(retry.current?.key!==key)retry.current={key,id:crypto.randomUUID()}
    try{
      const order=await api<{id:string;status:string}>(`${endpoint}/orders`,'POST',{...payload,request_id:retry.current.id})
      retry.current=null;setNotice(`${order.status} · ${order.id}`)
      setAccount(await api<Balance>(endpoint));onFilled?.()
    }catch(e){setError(failure(e))}finally{setBusy(false)}
  }
  return <section className="panel padded ticket"><div className="section-heading"><h2>Order ticket</h2><span className={`badge ${tradingMode === 'LIVE' ? 'amber' : ''}`}>{tradingMode}</span></div>
    <div className="ticket-symbol"><strong>{instrument.symbol}</strong><span className={liveLtp ? "live-tick" : ""}>{money(ltp)}</span><small>{instrument.exchange.toUpperCase()} · {instrument.kind}{derivative?` · ${instrument.lot_size} units / lot`:''}</small></div>
    {derivative&&<p className="contract-description">Expiry {instrument.expiry||'unavailable'}{instrument.kind==='OPTION'?` · ${instrument.strike} ${instrument.option_type}`:''}</p>}
    <form onSubmit={submit}><div className="side-toggle"><button type="button" className={side==='BUY'?'buy selected':''} onClick={()=>setSide('BUY')}>{future?'Buy / close short':'Buy'}</button><button type="button" className={side==='SELL'?'sell selected':''} onClick={()=>setSide('SELL')}>{future?'Sell / close long':'Sell holdings'}</button></div>
      <div className="form-row"><label>{derivative?'Lots':'Quantity'}<input aria-label={derivative?'Lots':'Quantity'} type="number" min="1" step="1" max={Math.floor(10000/(derivative?instrument.lot_size:1))} required value={amount} onChange={e=>setAmount(Number(e.target.value))}/></label><label>Order type<select value={type} onChange={e=>setType(e.target.value)}><option>MARKET</option>{!future&&<option>LIMIT</option>}</select></label></div>
      {type==='LIMIT'&&<label>Limit price<input required type="number" min={instrument.tick_size} step={instrument.tick_size} value={price} onChange={e=>setPrice(e.target.value)}/></label>}
      {derivative&&<p className="fine-print">{amount} lots × {instrument.lot_size} = {quantity} units</p>}
      <div className="ticket-estimate"><span>{future?'Contract notional':'Estimated value'}</span><strong>{money(value)}</strong></div>
      {future&&<div className="ticket-estimate"><span>Opening margin · 20%</span><strong>{money(value*.2)}</strong></div>}
      <div className="ticket-estimate"><span>Available {tradingMode === 'LIVE' ? 'live' : 'paper'} cash</span><strong>{money(account?.available)}</strong></div>
      <button className={`primary ${side==='SELL'?'sell-button':''}`} disabled={busy||!ltp||!supported}>{busy?<><span className="spinner"></span> Submitting…</>:`${side==='BUY'?'Buy':'Sell'} ${tradingMode === 'LIVE' ? 'live' : 'paper'} ${future?'futures':instrument.kind==='OPTION'?'option':'shares'}`}</button>
    </form>{!supported&&<p className="error"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>Select a tradable stock, ETF or derivative contract.</p>}{!ltp&&<p className="fine-print">Waiting for a usable price. Orders are unavailable until a quote arrives.</p>}
    {error&&<div className="error" role="alert"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>{error}</div>}{notice&&<div className="success" role="status"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M22 11.08V12a10 10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>{notice}</div>}
    {future?<p className="fine-print">{tradingMode === 'LIVE' ? 'Kotak Neo handles futures margins and daily settlement.' : 'Simulation reserves 20% of entry notional. This is an illustrative paper margin, not Kotak’s margin requirement. Market orders only; no daily settlement, automatic liquidation or expiry settlement. Close before expiry.'}</p>:<p className="fine-print">{tradingMode === 'LIVE' ? 'Live orders are sent to Kotak Neo via API.' : 'Virtual fills use the last available quote, including after market close. No fees or liquidity model. Sell closes owned shares or long options.'}</p>}
    <Link className="text-link" href="/trading/">View positions & orders →</Link>
  </section>
}
