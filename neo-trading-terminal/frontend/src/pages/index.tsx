import Link from 'next/link'
import { useEffect, useMemo, useState } from 'react'
import { ArrowUpRight, Search, X } from 'lucide-react'
import { api, failure, Instrument, money } from '@/lib/api'
import { companyName, exchangeName, shortSymbol } from '@/lib/instruments'
import { useQuotes } from '@/lib/useQuotes'
import { useTerminal } from '@/components/Layout'
import MarketTable from '@/components/MarketTable'

export default function Markets(){
  const {status}=useTerminal()
  const [query,setQuery]=useState(''),[exchange,setExchange]=useState(''),[kind,setKind]=useState('EQUITY'),[sort,setSort]=useState('name')
  const [offset,setOffset]=useState(0),[items,setItems]=useState<Instrument[]>([]),[total,setTotal]=useState(0),[loading,setLoading]=useState(true)
  const [errors,setErrors]=useState<{watch?:string;list?:string;action?:string}>({}),[watch,setWatch]=useState<Instrument[]>([])
  useEffect(()=>{let active=true;api<Instrument[]>('/watchlist').then(r=>{if(active){setWatch(r);setErrors(prev=>({...prev,watch:''}))}}).catch(e=>{if(active)setErrors(prev=>({...prev,watch:failure(e)}))});return()=>{active=false}},[])
  useEffect(()=>{let active=true;const timer=setTimeout(async()=>{setLoading(true);try{const r=await api<{items:Instrument[];total:number}>(`/instruments?q=${encodeURIComponent(query)}&exchange=${exchange}&kind=${kind}&sort=${sort}&offset=${offset}&limit=25`);if(active){setItems(r.items);setTotal(r.total);setErrors(prev=>({...prev,list:''}))}}catch(e){if(active)setErrors(prev=>({...prev,list:failure(e)}))}finally{if(active)setLoading(false)}},250);return()=>{active=false;clearTimeout(timer)}},[query,exchange,kind,sort,offset,status?.catalogue.updated_at])
  const quoteIds=useMemo(()=>Array.from(new Set([...watch,...items].map(i=>i.id))).slice(0,50),[watch,items])
  const {quotes,error:quoteError,updatedAt:stamp}=useQuotes(quoteIds)
  const error=errors.action||errors.watch||errors.list||quoteError
  async function star(i:Instrument){setErrors(prev=>({...prev,action:''}));try{const added=watch.some(w=>w.id===i.id);setWatch(await api<Instrument[]>(added?`/watchlist/${encodeURIComponent(i.id)}`:'/watchlist',added?'DELETE':'POST',added?undefined:{ids:[i.id]}))}catch(e){setErrors(prev=>({...prev,action:failure(e)}))}}
  return <div className="market-page">
    <div className="market-page-heading"><div><p className="market-eyebrow">YOUR DAILY MARKET VIEW</p><h1>Market overview<span>.</span></h1><p>Follow the companies you care about, all in one place.</p></div><Link className="market-primary-link" href="/trading/">Your portfolio <ArrowUpRight size={17}/></Link></div>
    <div className="market-shortcuts"><Link href="/stocks/"><span className="shortcut-icon">↗</span><div><h2>Stocks & ETFs</h2><p>Discover Indian companies</p></div><ArrowUpRight size={20}/></Link><Link href="/indices/"><span className="shortcut-icon">⌁</span><div><h2>Indices & F&O</h2><p>Explore indices and contracts</p></div><ArrowUpRight size={20}/></Link></div>
    <section className="market-watch-section" aria-label="Your watchlist"><div className="market-section-heading"><div><h2>Your watchlist</h2><p>A closer look at your saved companies</p></div><span>{watch.length} saved</span></div>
      <div className="market-watch-grid">{watch.slice(0,4).map(i=>{const q=quotes[i.id];return <Link className="market-watch-card" href={`/instrument/?instrument=${encodeURIComponent(i.id)}`} key={i.id}><div><span>{exchangeName(i.exchange)}</span><ArrowUpRight size={16}/></div><h3>{companyName(i)}</h3><small>{shortSymbol(i)}</small><strong>{money(q?.ltp)}</strong><span className={q?(q.change_pct>0?'positive':q.change_pct<0?'negative':'muted'):'muted'}>{q?`${q.change_pct>0?'+':''}${q.change_pct.toFixed(2)}%`:'Price unavailable'}<small>Last available quote</small></span></Link>})}{!watch.length&&<div className="market-watch-empty"><h3>Make this space yours</h3><p>Tap the star beside a company to follow it here.</p><Link className="text-link" href="/stocks/">Explore companies →</Link></div>}</div>
    </section>
    <section className="market-list-panel" aria-label="Discover the market"><div className="market-list-heading"><div><h2>Discover the market</h2><p>Search by company name or stock symbol.</p></div><span className="market-freshness"><span className="dot green"/>{stamp?`Updated ${stamp} IST`:'Waiting for quotes'}</span></div>
      <div className="market-browse-toolbar"><label className="market-search compact"><Search size={18}/><input aria-label="Search Indian stocks" placeholder="Find a company…" value={query} onChange={e=>{setQuery(e.target.value);setOffset(0)}}/>{query&&<button aria-label="Clear market search" onClick={()=>{setQuery('');setOffset(0)}}><X size={16}/></button>}</label><select aria-label="Exchange" value={exchange} onChange={e=>{setExchange(e.target.value);setOffset(0)}}><option value="">All exchanges</option>{['nse_cm','bse_cm','nse_fo','bse_fo'].map(s=><option key={s} value={s}>{exchangeName(s)}</option>)}</select><select aria-label="Instrument type" value={kind} onChange={e=>{setKind(e.target.value);setOffset(0)}}><option value="EQUITY">Shares</option><option value="ETF">ETFs</option><option value="INDEX">Indices</option><option value="OPTION">Options</option><option value="FUTURE">Futures</option><option value="">All instruments</option></select><select aria-label="Sort instruments" value={sort} onChange={e=>{setSort(e.target.value);setOffset(0)}}><option value="name">Company A–Z</option><option value="name_desc">Company Z–A</option><option value="symbol">Stock symbol</option></select></div>
      {error&&<p className="error" role="alert">{error}</p>}<MarketTable items={items} quotes={quotes} watch={watch} onWatch={i=>void star(i)} loading={loading}/>
      <div className="market-pagination"><span>{total.toLocaleString('en-IN')} results · {total?offset+1:0}–{Math.min(offset+25,total)}</span><div><button disabled={loading||!offset} onClick={()=>setOffset(Math.max(0,offset-25))}>Previous</button><button disabled={loading||offset+25>=total} onClick={()=>setOffset(offset+25)}>Next</button></div></div>
    </section><p className="market-footnote">{status?.market_data_source==='kotak'?'Kotak Neo prices':'Illustrative paper prices'} · Refreshes every 5 seconds · Unavailable prices appear as —</p>
  </div>
}
