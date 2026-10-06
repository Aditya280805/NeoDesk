import { useRouter } from 'next/router'
import { useEffect, useState } from 'react'
import dynamic from 'next/dynamic'
import Link from 'next/link'
import InstrumentPicker from '@/components/InstrumentPicker'
import { History } from '@/components/PriceChart'
import { api, failure, money } from '@/lib/api'
import { useTerminal } from '@/components/Layout'
const PriceChart=dynamic(()=>import('@/components/PriceChart'),{ssr:false})
export default function Charts(){
  const router=useRouter(),{status}=useTerminal()
  const id=typeof router.query.instrument==='string'?router.query.instrument:'nse_cm|1333'
  const [interval,setIntervalValue]=useState('D'),[data,setData]=useState<History|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false)
  useEffect(()=>{
    let active=true,running=false
    async function load(){
      if(running)return
      running=true;setBusy(true)
      try{
        const days=interval==='D'?365:interval==='60min'?90:interval==='15min'?60:30
        const r=await api<History>(`/market/history?instrument_id=${encodeURIComponent(id)}&interval=${interval}&days=${days}`)
        if(active){setData(r);setError('')}
      }catch(e){if(active){setData(null);setError(failure(e))}}
      finally{running=false;if(active)setBusy(false)}
    }
    const initial=setTimeout(()=>{setData(null);void load()},0)
    const timer=setInterval(load,60000)
    return()=>{active=false;clearTimeout(initial);clearInterval(timer)}
  },[id,interval,status?.market_data_source])
  const last=data?.candles.at(-1)
  return <><div className="page-heading"><div><p className="eyebrow">PRICE & MOMENTUM</p><h1>Chart workspace<span className="accent">.</span></h1><p>Broker candles with moving averages and Wilder RSI.</p></div><Link className="button primary" href={`/instrument/?instrument=${encodeURIComponent(id)}`}>Open paper ticket ↗</Link></div><div className="chart-layout"><section className="panel chart-card"><div className="section-heading"><div><h2>{id}</h2><strong>{money(last?.close)}</strong></div><select aria-label="Chart interval" value={interval} onChange={e=>setIntervalValue(e.target.value)}>{['1min','5min','15min','60min','D'].map(v=><option key={v} value={v}>{v==='D'?'Daily':v}</option>)}</select></div>{busy&&<p className="muted">Loading candles…</p>}{error&&<p className="error">{error}</p>}{data&&<PriceChart data={data} instrumentId={id}/>}<p className={data?.partial?'error':'fine-print'}>{data?.note} {data?.interval==='D'?'Moving averages use daily candles (DMA).':'Moving averages use the selected candle interval.'} RSI: {data?.indicators.rsi14.at(-1)?.toFixed(2)??'—'}. Missing history stays empty; no broker gaps are filled with synthetic prices.</p></section><section className="panel padded"><h2>Select instrument</h2><InstrumentPicker onSelect={i=>router.push(`/charts/?instrument=${encodeURIComponent(i.id)}`)}/><p className="fine-print">Charts refresh every 60 seconds. Daily charts request one year in broker-supported batches. SMA 200 appears when at least 200 daily candles are available; newly listed instruments may have less history.</p></section></div></>
}
