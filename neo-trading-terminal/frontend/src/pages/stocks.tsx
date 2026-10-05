import { useEffect, useState } from 'react'
import Link from 'next/link'
import { Search, Star } from 'lucide-react'
import { api, failure, Instrument, money } from '@/lib/api'
import { useQuotes } from '@/lib/useQuotes'
import { useTerminal } from '@/components/Layout'
import TradeTicket from '@/components/TradeTicket'
import ActivityList from '@/components/ActivityList'

export default function Stocks(){
  const {status}=useTerminal()
  const [query,setQuery]=useState(''),[exchange,setExchange]=useState(''),[kind,setKind]=useState('EQUITY'),[sort,setSort]=useState('symbol'),[offset,setOffset]=useState(0)
  const [rows,setRows]=useState<Instrument[]>([]),[total,setTotal]=useState(0),[selected,setSelected]=useState<Instrument|null>(null),[error,setError]=useState(''),[loading,setLoading]=useState(true),[watch,setWatch]=useState<Instrument[]>([])
  const {quotes,error:quoteError}=useQuotes([...rows.map(i=>i.id),...(selected?[selected.id]:[])])
  useEffect(()=>{let active=true;api<Instrument[]>('/watchlist').then(r=>{if(active)setWatch(r)}).catch(()=>{});return()=>{active=false}},[])
  useEffect(()=>{let active=true;const timer=setTimeout(async()=>{setLoading(true);try{const r=await api<{items:Instrument[];total:number}>(`/stocks?q=${encodeURIComponent(query)}&exchange=${exchange}&kind=${kind}&sort=${sort}&offset=${offset}&limit=25`);if(active){setRows(r.items);setTotal(r.total);setError('')}}catch(e){if(active){setRows([]);setError(failure(e))}}finally{if(active)setLoading(false)}},250);return()=>{active=false;clearTimeout(timer)}},[query,exchange,kind,sort,offset,status?.catalogue.updated_at])
  async function star(i:Instrument){try{const exists=watch.some(w=>w.id===i.id);setWatch(await api<Instrument[]>(exists?`/watchlist/${encodeURIComponent(i.id)}`:'/watchlist',exists?'DELETE':'POST',exists?undefined:{ids:[i.id]}))}catch(e){setError(failure(e))}}
  return <><div className="page-heading"><div><p className="eyebrow">OWN A PIECE OF THE MARKET</p><h1>Indian stocks<span className="accent">.</span></h1><p>Find NSE & BSE shares. Choose your exchange. Place a paper trade.</p></div><span className="badge">₹1,00,000 PAPER ACCOUNT</span></div>
    <div className="discovery-search"><Search size={22}/><input aria-label="Search stocks" placeholder="Search any company or symbol — HDFC Bank, RELIANCE, TCS…" value={query} onChange={e=>{setQuery(e.target.value);setOffset(0)}}/><span>STOCKS & ETFs</span></div>
    <ActivityList scope="stocks" onSelect={setSelected}/>
    <div className={selected?'discovery-layout':'discovery-layout wide'}><section className="panel"><div className="toolbar"><h2>{total.toLocaleString('en-IN')} listings</h2><select aria-label="Stock exchange" value={exchange} onChange={e=>{setExchange(e.target.value);setOffset(0)}}><option value="">NSE + BSE</option><option value="nse_cm">NSE</option><option value="bse_cm">BSE</option></select><select aria-label="Stock type" value={kind} onChange={e=>{setKind(e.target.value);setOffset(0)}}><option value="EQUITY">Shares</option><option value="ETF">ETFs</option><option value="">Shares + ETFs</option></select><select aria-label="Sort stocks" value={sort} onChange={e=>{setSort(e.target.value);setOffset(0)}}><option value="symbol">Name A–Z</option><option value="symbol_desc">Name Z–A</option><option value="exchange">Exchange</option></select></div>
      {(error||quoteError)&&<p className="error">{error||quoteError}</p>}{loading&&<p className="padded muted">Searching…</p>}
      <div className="table-scroll"><table><thead><tr><th></th><th>COMPANY / SYMBOL</th><th>EXCHANGE</th><th className="numeric">PRICE</th><th className="numeric">CHANGE</th><th></th></tr></thead><tbody>{rows.map(i=><tr key={i.id} className={selected?.id===i.id?'selected-row':''}><td><button className={`star ${watch.some(w=>w.id===i.id)?'on':''}`} aria-label={`Watch ${i.symbol}`} onClick={()=>star(i)}><Star size={16}/></button></td><td><button className="symbol-link" onClick={()=>setSelected(i)}>{i.symbol}</button><small className="instrument-name">{i.name}</small></td><td><span className="tag">{i.exchange==='nse_cm'?'NSE':'BSE'} · {i.kind}</span></td><td className="numeric">{money(quotes[i.id]?.ltp)}</td><td className={`numeric ${(quotes[i.id]?.change_pct??0)>=0?'positive':'negative'}`}>{quotes[i.id]?`${quotes[i.id].change_pct.toFixed(2)}%`:'—'}</td><td><button className="text-link" onClick={()=>setSelected(i)}>Trade →</button></td></tr>)}</tbody></table></div>
      {!loading&&!rows.length&&<div className="empty-state">No matching stocks.<small>Try another symbol or exchange. Import the catalogue in Connections for full broker coverage.</small></div>}
      <div className="pagination"><span>{total?offset+1:0}–{Math.min(offset+25,total)} of {total.toLocaleString('en-IN')}</span><div><button disabled={!offset} onClick={()=>setOffset(Math.max(0,offset-25))}>Previous</button><button disabled={offset+25>=total} onClick={()=>setOffset(offset+25)}>Next</button></div></div>
    </section>{selected&&<div className="selection-column"><div className="selection-tools"><Link className="text-link" href={`/charts/?instrument=${encodeURIComponent(selected.id)}`}>Open {selected.symbol} chart ↗</Link><button aria-label="Close stock ticket" onClick={()=>setSelected(null)}>×</button></div><TradeTicket key={selected.id} instrument={selected} quote={quotes[selected.id]}/></div>}</div>
    <p className="fine-print">Catalogue coverage follows Kotak. NSE/BSE listings remain separate for order routing. Quotes refresh every 5 seconds; an unavailable price is shown as —.</p>
  </>
}
