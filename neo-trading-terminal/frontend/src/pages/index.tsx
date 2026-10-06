import Link from 'next/link'
import { useEffect, useState } from 'react'
import { ArrowDownUp, Search, Star, ArrowUpRight } from 'lucide-react'
import { api, failure, Instrument, money, Quote } from '@/lib/api'
import { useTerminal } from '@/components/Layout'

export default function Markets(){
  const {status}=useTerminal()
  const [query,setQuery]=useState(''),[exchange,setExchange]=useState(''),[kind,setKind]=useState('EQUITY'),[sort,setSort]=useState('symbol')
  const [offset,setOffset]=useState(0),[items,setItems]=useState<Instrument[]>([]),[total,setTotal]=useState(0),[error,setError]=useState('')
  const [quotes,setQuotes]=useState<Record<string,Quote>>({}),[watch,setWatch]=useState<Instrument[]>([]),[watchQuotes,setWatchQuotes]=useState<Quote[]>([]),[stamp,setStamp]=useState('')
  useEffect(()=>{let active=true;api<Instrument[]>('/watchlist').then(r=>{if(active)setWatch(r)}).catch(e=>{if(active)setError(failure(e))});return()=>{active=false}},[])
  useEffect(()=>{
    let active=true
    const timer=setTimeout(()=>{api<{items:Instrument[];total:number}>(`/instruments?q=${encodeURIComponent(query)}&exchange=${exchange}&kind=${kind}&sort=${sort}&offset=${offset}&limit=25`).then(r=>{if(active){setItems(r.items);setTotal(r.total);setError('')}}).catch(e=>{if(active)setError(failure(e))})},250)
    return()=>{active=false;clearTimeout(timer)}
  },[query,exchange,kind,sort,offset,status?.catalogue.updated_at])
  useEffect(()=>{
    let active=true,running=false
    async function update(){
      if(running)return;running=true
      try{
        const ids=Array.from(new Set([...items,...watch].map(i=>i.id))).slice(0,50)
        const result=await api<Quote[]>('/market/quotes','POST',{ids})
        if(active){setQuotes(Object.fromEntries(result.map(q=>[q.id,q])));setWatchQuotes(result.filter(q=>watch.some(w=>w.id===q.id)));setStamp(new Date().toLocaleTimeString('en-IN',{timeZone:'Asia/Kolkata'}));setError('')}
      }catch(e){if(active){setQuotes({});setWatchQuotes([]);setError(failure(e))}}finally{running=false}
    }
    void update();const timer=setInterval(update,5000);return()=>{active=false;clearInterval(timer)}
  },[items,watch,status?.market_data_source])
  async function star(i:Instrument){try{const added=watch.some(w=>w.id===i.id);setWatch(await api<Instrument[]>(added?`/watchlist/${encodeURIComponent(i.id)}`:'/watchlist',added?'DELETE':'POST',added?undefined:{ids:[i.id]}))}catch(e){setError(failure(e))}}
  return <>
    <div className="page-heading"><div><p className="eyebrow">THE INDIAN MARKET, IN FOCUS</p><h1>Market overview<span className="accent">.</span></h1><p>Explore instruments. Follow your watchlist. Find your next idea.</p></div><Link className="button primary" href="/trading/">Open paper terminal <ArrowUpRight size={16}/></Link></div>
    <div className="overview-links"><Link href="/stocks/"><span>→</span><h2>Stocks & ETFs</h2><p>Search Indian shares, choose an exchange and open a paper ticket.</p></Link><Link href="/indices/"><span>→</span><h2>Indices & F&O</h2><p>Explore index futures and options by expiry, strike and lot size.</p></Link></div><section className="metrics">{watchQuotes.slice(0,4).map(q=><Link className="metric" href={`/instrument/?instrument=${encodeURIComponent(q.id)}`} key={q.id}><div><span className="metric-label">{q.symbol}</span><ArrowUpRight size={14}/></div><strong>{money(q.ltp)}</strong><span className={q.change_pct>=0?'positive':'negative'}>{q.change_pct>=0?'+':''}{q.change_pct.toFixed(2)}% <small>last available quote</small></span></Link>)}{watchQuotes.length===0&&<div className="metric"><span className="metric-label">WATCHLIST</span><strong>Build your view</strong><p>Add instruments using the star below.</p></div>}</section>
    <div className="section-heading"><div><h2>Discover the market</h2><p>{status?.catalogue.total.toLocaleString('en-IN')||'—'} broker instruments · {status?.catalogue.updated_at?'Catalogue imported from Kotak':'Starter catalogue — connect and sync to load the full list'}</p></div><span className="status-small">{stamp?`Fetched ${stamp} IST`:'Waiting for prices'}</span></div>
    <div className="panel"><div className="toolbar"><div className="search-field"><Search size={17}/><input aria-label="Search Indian stocks" placeholder="Search symbol, company, or underlying" value={query} onChange={e=>{setQuery(e.target.value);setOffset(0)}}/></div><select aria-label="Exchange" value={exchange} onChange={e=>{setExchange(e.target.value);setOffset(0)}}><option value="">All exchanges</option>{['nse_cm','bse_cm','nse_fo','bse_fo'].map(s=><option key={s} value={s}>{s.toUpperCase()}</option>)}</select><select aria-label="Instrument type" value={kind} onChange={e=>{setKind(e.target.value);setOffset(0)}}><option value="">All instruments</option>{['EQUITY','ETF','INDEX','OPTION','FUTURE','OTHER'].map(s=><option key={s}>{s}</option>)}</select><select aria-label="Sort instruments" value={sort} onChange={e=>{setSort(e.target.value);setOffset(0)}}><option value="symbol">Symbol A–Z</option><option value="symbol_desc">Symbol Z–A</option><option value="exchange">Exchange</option><option value="kind">Type</option></select></div>
    {error&&<p className="error" role="alert">{error}</p>}<div className="table-scroll"><table><thead><tr><th></th><th>INSTRUMENT <ArrowDownUp size={12}/></th><th>EXCHANGE</th><th>TYPE</th><th className="numeric">LAST PRICE</th><th className="numeric">CHANGE</th><th className="numeric">LOT SIZE</th><th></th></tr></thead><tbody>{items.map(i=><tr key={i.id}><td><button aria-label={`Watch ${i.symbol}`} className={`star ${watch.some(w=>w.id===i.id)?'on':''}`} onClick={()=>star(i)}><Star size={15}/></button></td><td><Link className="symbol" href={`/instrument/?instrument=${encodeURIComponent(i.id)}`}>{i.symbol}</Link><small className="instrument-name">{i.name}</small></td><td><span className="tag">{i.exchange.toUpperCase()}</span></td><td>{i.kind}</td><td className="numeric">{money(quotes[i.id]?.ltp)}</td><td className={`numeric ${(quotes[i.id]?.change_pct??0)>=0?'positive':'negative'}`}>{quotes[i.id]?`${quotes[i.id].change_pct.toFixed(2)}%`:'—'}</td><td className="numeric">{i.lot_size}</td><td><Link className="text-link" href={`/instrument/?instrument=${encodeURIComponent(i.id)}`}>Trade ↗</Link></td></tr>)}</tbody></table>{items.length===0&&<div className="empty-state">No matching instruments. Try another filter or sync the catalogue in Connections.</div>}</div><div className="pagination"><span>{total.toLocaleString('en-IN')} results · showing {total?offset+1:0}–{Math.min(offset+25,total)}</span><div><button disabled={offset===0} onClick={()=>setOffset(Math.max(0,offset-25))}>Previous</button><button disabled={offset+25>=total} onClick={()=>setOffset(offset+25)}>Next</button></div></div></div>
    <div className="info-strip"><span className="dot green"/><span>Prices refresh every 5 seconds while this page is open. Closed markets show the last available broker quote.</span><Link href="/connections/">Manage data connection →</Link></div>
  </>
}
