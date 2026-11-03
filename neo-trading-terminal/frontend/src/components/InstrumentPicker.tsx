import { useEffect, useState } from 'react'
import { api, Instrument } from '@/lib/api'
import { companyName, exchangeName, shortSymbol } from '@/lib/instruments'

export default function InstrumentPicker({onSelect}:{onSelect:(i:Instrument)=>void}) {
  const [q,setQ]=useState(''),[items,setItems]=useState<Instrument[]>([]),[error,setError]=useState('')
  useEffect(()=>{let active=true;const timer=setTimeout(()=>{api<{items:Instrument[]}>(`/instruments?q=${encodeURIComponent(q)}&limit=8`).then(r=>{if(active){setItems(r.items);setError('')}}).catch(()=>{if(active)setError('Instrument search unavailable.')})},250);return()=>{active=false;clearTimeout(timer)}},[q])
  return <div className="picker"><input aria-label="Search instruments" placeholder="Search a company or symbol…" value={q} onChange={e=>setQ(e.target.value)}/>{error&&<p className="error">{error}</p>}<div className="picker-results">{items.map(i=><button key={i.id} onClick={()=>onSelect(i)}><b>{companyName(i)}</b><small>{shortSymbol(i)} · {exchangeName(i.exchange)}</small></button>)}</div></div>
}
