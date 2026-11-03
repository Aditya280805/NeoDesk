import { useEffect, useState } from 'react'
import { useRouter } from 'next/router'
import { Search, SlidersHorizontal, X } from 'lucide-react'
import { api, failure, Instrument } from '@/lib/api'
import { useQuotes } from '@/lib/useQuotes'
import { useTerminal } from '@/components/Layout'
import ActivityList from '@/components/ActivityList'
import MarketTable from '@/components/MarketTable'

export default function Stocks(){
  const {status}=useTerminal(),router=useRouter()
  const [query,setQuery]=useState(''),[exchange,setExchange]=useState(''),[kind,setKind]=useState('EQUITY'),[sort,setSort]=useState('name'),[offset,setOffset]=useState(0)
  const [rows,setRows]=useState<Instrument[]>([]),[total,setTotal]=useState(0),[error,setError]=useState(''),[loading,setLoading]=useState(true),[watch,setWatch]=useState<Instrument[]>([])
  const {quotes,error:quoteError}=useQuotes(rows.map(i=>i.id))
  useEffect(()=>{let active=true;api<Instrument[]>('/watchlist').then(r=>{if(active)setWatch(r)}).catch(e=>{if(active)setError(failure(e))});return()=>{active=false}},[])
  useEffect(()=>{let active=true;const timer=setTimeout(async()=>{setLoading(true);try{const r=await api<{items:Instrument[];total:number}>(`/stocks?q=${encodeURIComponent(query)}&exchange=${exchange}&kind=${kind}&sort=${sort}&offset=${offset}&limit=25`);if(active){setRows(r.items);setTotal(r.total);setError('')}}catch(e){if(active){setRows([]);setError(failure(e))}}finally{if(active)setLoading(false)}},250);return()=>{active=false;clearTimeout(timer)}},[query,exchange,kind,sort,offset,status?.catalogue.updated_at])
  async function star(i:Instrument){try{const exists=watch.some(w=>w.id===i.id);setWatch(await api<Instrument[]>(exists?`/watchlist/${encodeURIComponent(i.id)}`:'/watchlist',exists?'DELETE':'POST',exists?undefined:{ids:[i.id]}))}catch(e){setError(failure(e))}}
  const open=(i:Instrument)=>void router.push(`/instrument/?instrument=${encodeURIComponent(i.id)}`)
  return <div className="market-page">
    <div className="market-page-heading"><div><p className="market-eyebrow">EXPLORE / INDIAN EQUITIES</p><h1>Discover Indian stocks<span>.</span></h1><p>Browse NSE and BSE companies by name, then open a listing for details.</p></div><span className="market-coverage"><span className="dot green"/>NSE & BSE</span></div>
    <label className="market-search"><Search size={21}/><input aria-label="Search stocks" placeholder="Search a company or stock symbol…" value={query} onChange={e=>{setQuery(e.target.value);setOffset(0)}}/>{query&&<button aria-label="Clear stock search" onClick={()=>{setQuery('');setOffset(0)}}><X size={17}/></button>}<span className="search-hint">e.g. HDFC Bank</span></label>
    <ActivityList scope="stocks" onSelect={open}/>
    <section className="market-list-panel" aria-label="Indian stock listings">
      <div className="market-list-heading"><div><h2>All companies <span>{total.toLocaleString('en-IN')}</span></h2><p>Browse shares and ETFs by company name.</p></div><div className="market-filter-summary"><SlidersHorizontal size={15}/>Your market, your view</div></div>
      <div className="market-filters"><div className="exchange-segments" role="group" aria-label="Stock exchange">{[['','All exchanges'],['nse_cm','NSE'],['bse_cm','BSE']].map(([value,label])=><button key={value} aria-pressed={exchange===value} className={exchange===value?'active':''} onClick={()=>{setExchange(value);setOffset(0)}}>{label}</button>)}</div><div className="market-filter-selects"><label>Show<select aria-label="Stock type" value={kind} onChange={e=>{setKind(e.target.value);setOffset(0)}}><option value="EQUITY">Shares</option><option value="ETF">ETFs</option><option value="">Shares & ETFs</option></select></label><label>Sort by<select aria-label="Sort stocks" value={sort} onChange={e=>{setSort(e.target.value);setOffset(0)}}><option value="name">Company A–Z</option><option value="name_desc">Company Z–A</option><option value="symbol">Stock symbol</option></select></label></div></div>
      {(error||quoteError)&&<p className="error" role="alert">{error||quoteError}</p>}
      <MarketTable items={rows} quotes={quotes} watch={watch} onWatch={i=>void star(i)} loading={loading}/>
      <div className="market-pagination"><span>Showing {total?offset+1:0}–{Math.min(offset+25,total)} of {total.toLocaleString('en-IN')} listings</span><div><button disabled={loading||!offset} onClick={()=>setOffset(Math.max(0,offset-25))}>Previous</button><button disabled={loading||offset+25>=total} onClick={()=>setOffset(offset+25)}>Next</button></div></div>
    </section><p className="market-footnote">Separate NSE and BSE listings are retained for accurate trading. Prices refresh every 5 seconds; closed markets show the last available quote.</p>
  </div>
}
