import { useEffect, useState } from 'react'
import Link from 'next/link'
import { Search } from 'lucide-react'
import { api, failure, Instrument, money } from '@/lib/api'
import { useQuotes } from '@/lib/useQuotes'
import { useTerminal } from '@/components/Layout'
import ActivityList from '@/components/ActivityList'
import { useRouter } from 'next/router'

type IndexItem={id:string;symbol:string;name:string;exchange:string;spot:Instrument|null;options_count:number;futures_count:number}
export default function Indices(){
  const {status}=useTerminal(),router=useRouter()
  const [query,setQuery]=useState(''),[indices,setIndices]=useState<IndexItem[]>([]),[error,setError]=useState(''),[loading,setLoading]=useState(true)
  const {quotes,error:quoteError}=useQuotes(indices.flatMap(i=>i.spot?[i.spot.id]:[]))
  useEffect(()=>{let active=true;api<IndexItem[]>('/indices').then(r=>{if(active){setIndices(r);setError('')}}).catch(e=>{if(active)setError(failure(e))}).finally(()=>{if(active)setLoading(false)});return()=>{active=false}},[status?.catalogue.updated_at])
  const term=query.toLowerCase().replace(/\s/g,'')
  const visible=indices.filter(i=>(i.name+i.symbol).toLowerCase().replace(/\s/g,'').includes(term))
  return <><div className="page-heading"><div><p className="eyebrow">THE BIGGER PICTURE</p><h1>Indices & F&O<span className="accent">.</span></h1><p>Open an index to explore its price chart, futures and options.</p></div><span className="badge">NSE & BSE</span></div>
    <div className="discovery-search"><Search size={22}/><input aria-label="Search indices" placeholder="Search Nifty 50, Bank Nifty, Sensex…" value={query} onChange={e=>setQuery(e.target.value)}/></div>
    {(error||quoteError)&&<p className="error">{error||quoteError}</p>}
    <div className="index-grid">{visible.map(i=>{const q=i.spot?quotes[i.spot.id]:undefined;return <Link className="index-card" key={i.id} href={i.spot?`/instrument/?instrument=${encodeURIComponent(i.spot.id)}`:'/connections/'}><span className="index-card-top"><span>{i.name}</span><small>{i.exchange==='nse_fo'?'NSE':'BSE'}</small></span><strong>{money(q?.ltp)}</strong><span className={(q?.change_pct??0)>=0?'positive':'negative'}>{q?`${q.change_pct.toFixed(2)}%`:'Price unavailable'}</span><small>{i.futures_count} futures · {i.options_count.toLocaleString('en-IN')} options →</small></Link>})}</div>
    {!visible.length&&<div className="panel empty-state">{loading?'Loading indices…':'No matching indices. Try another name or sync the catalogue.'}</div>}
    <ActivityList scope="indices" onSelect={i=>void router.push(`/instrument/?instrument=${encodeURIComponent(i.id)}`)}/>
    <p className="fine-print">Index levels are references. Open an index and choose an active futures or options contract to trade.</p>
  </>
}
