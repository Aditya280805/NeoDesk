import { useEffect, useState } from 'react'
import Link from 'next/link'
import { Search } from 'lucide-react'
import { api, failure, Instrument, money } from '@/lib/api'
import { useQuotes } from '@/lib/useQuotes'
import { useTerminal } from '@/components/Layout'
import TradeTicket from '@/components/TradeTicket'
import ActivityList from '@/components/ActivityList'

type IndexItem={id:string;symbol:string;name:string;exchange:string;spot:Instrument|null;options_count:number;futures_count:number}
type Contracts={items:Instrument[];total:number;expiries:string[];expiry:string}
export default function Indices(){
  const {status}=useTerminal()
  const [query,setQuery]=useState(''),[indices,setIndices]=useState<IndexItem[]>([]),[selected,setSelected]=useState<IndexItem|null>(null)
  const [kind,setKind]=useState('OPTION'),[expiry,setExpiry]=useState(''),[option,setOption]=useState(''),[strike,setStrike]=useState(''),[offset,setOffset]=useState(0)
  const [contracts,setContracts]=useState<Contracts|null>(null),[ticket,setTicket]=useState<Instrument|null>(null),[error,setError]=useState(''),[loading,setLoading]=useState(false)
  const {quotes,error:quoteError}=useQuotes([...indices.flatMap(i=>i.spot?[i.spot.id]:[]),...(contracts?.items.map(i=>i.id)||[]),...(ticket?[ticket.id]:[])])
  useEffect(()=>{let active=true;api<IndexItem[]>('/indices').then(r=>{if(active){setIndices(r);setError('')}}).catch(e=>{if(active)setError(failure(e))});return()=>{active=false}},[status?.catalogue.updated_at])
  useEffect(()=>{
    if(!selected)return
    let active=true
    const timer=setTimeout(async()=>{setLoading(true);setContracts(null);try{const params=new URLSearchParams({underlying:selected.symbol,exchange:selected.exchange,kind,expiry,option_type:option,offset:String(offset),limit:'24'});if(strike&&kind==='OPTION')params.set('strike',strike);const r=await api<Contracts>(`/contracts?${params}`);if(active){setContracts(r);setError('')}}catch(e){if(active)setError(failure(e))}finally{if(active)setLoading(false)}},200)
    return()=>{active=false;clearTimeout(timer)}
  },[selected,kind,expiry,option,strike,offset,status?.catalogue.updated_at])
  function choose(i:IndexItem,nextKind='OPTION'){setSelected(i);setKind(nextKind);setExpiry('');setOption('');setStrike('');setOffset(0);setTicket(null);setContracts(null)}
  function activitySelect(i:Instrument){const index=indices.find(n=>n.symbol===i.underlying&&n.exchange===i.exchange);if(index){choose(index,'FUTURE');setTicket(i)}}
  const term=query.toLowerCase().replace(/\s/g,'')
  const visible=indices.filter(i=>(i.name+i.symbol).toLowerCase().replace(/\s/g,'').includes(term))
  return <><div className="page-heading"><div><p className="eyebrow">FOLLOW THE INDEX. CHOOSE THE CONTRACT.</p><h1>Indices & F&O<span className="accent">.</span></h1><p>Discover index levels, then explore their listed futures and options.</p></div><span className="badge">NSE & BSE DERIVATIVES</span></div>
    <div className="discovery-search"><Search size={22}/><input aria-label="Search indices" placeholder="Search an index — Nifty 50, Bank Nifty, Sensex…" value={query} onChange={e=>setQuery(e.target.value)}/><span>INDEX SEARCH</span></div>
    <div className="index-grid">{visible.map(i=>{const q=i.spot?quotes[i.spot.id]:undefined;return <button className={`index-card ${selected?.id===i.id?'selected':''}`} key={i.id} onClick={()=>choose(i,i.options_count?'OPTION':'FUTURE')}><span className="index-card-top"><span>{i.name}</span><small>{i.exchange==='nse_fo'?'NSE':'BSE'}</small></span><strong>{money(q?.ltp)}</strong><span className={(q?.change_pct??0)>=0?'positive':'negative'}>{q?`${q.change_pct.toFixed(2)}%`:'Price unavailable'}</span><small>{i.futures_count} futures · {i.options_count.toLocaleString('en-IN')} options →</small></button>})}</div>
    {!visible.length&&<div className="panel empty-state">No matching indices in the imported catalogue.<small>Try the symbol or refresh the catalogue in Connections.</small></div>}
    <ActivityList scope="indices" onSelect={activitySelect}/>
    {(error||quoteError)&&<p className="error">{error||quoteError}</p>}
    {selected?<><div className="section-heading spaced"><div><p className="eyebrow">{selected.exchange.toUpperCase()}</p><h2>{selected.name} contracts</h2></div>{selected.spot&&<Link className="text-link" href={`/charts/?instrument=${encodeURIComponent(selected.spot.id)}`}>View index chart ↗</Link>}</div>
      <div className={ticket?'discovery-layout':'discovery-layout wide'}><section className="panel"><div className="contract-tabs" role="tablist" aria-label="Derivative type">{['OPTION','FUTURE'].map(k=><button role="tab" aria-selected={kind===k} className={kind===k?'active':''} key={k} onClick={()=>{setKind(k);setExpiry('');setOption('');setStrike('');setOffset(0);setTicket(null)}}>{k==='OPTION'?'Options':'Futures'}</button>)}</div>
        <div className="toolbar"><label>Expiry<select aria-label="Contract expiry" value={expiry} onChange={e=>{setExpiry(e.target.value);setOffset(0);setTicket(null)}}><option value="">{kind==='OPTION'?`Nearest available${contracts?.expiry?' · '+contracts.expiry:''}`:'All active expiries'}</option>{contracts?.expiries.map(d=><option key={d}>{d}</option>)}</select></label>{kind==='OPTION'&&<><label>Option type<select value={option} onChange={e=>{setOption(e.target.value);setOffset(0)}}><option value="">Calls + puts</option><option value="CE">Calls (CE)</option><option value="PE">Puts (PE)</option></select></label><label>Strike<input type="number" min="0" step="any" placeholder="Any strike" value={strike} onChange={e=>{setStrike(e.target.value);setOffset(0)}}/></label></>}</div>
        {loading?<div className="empty-state">Loading active contracts…</div>:<div className="table-scroll"><table><thead><tr><th>CONTRACT</th><th>EXPIRY</th>{kind==='OPTION'&&<th>STRIKE / TYPE</th>}<th className="numeric">LOT</th><th className="numeric">PRICE</th><th></th></tr></thead><tbody>{contracts?.items.map(i=><tr key={i.id} className={ticket?.id===i.id?'selected-row':''}><td><button className="symbol-link" onClick={()=>setTicket(i)}>{i.symbol}</button></td><td>{i.expiry}</td>{kind==='OPTION'&&<td><span className={i.option_type==='CE'?'positive':'negative'}>{i.strike.toLocaleString('en-IN')} {i.option_type}</span></td>}<td className="numeric">{i.lot_size}</td><td className="numeric">{money(quotes[i.id]?.ltp)}</td><td><button className="text-link" onClick={()=>setTicket(i)}>Trade →</button></td></tr>)}</tbody></table></div>}
        {!loading&&!contracts?.items.length&&<div className="empty-state">No active contracts match these filters.<small>Change the expiry or strike, or sync the latest catalogue.</small></div>}
        <div className="pagination"><span>{contracts?.total??0} contracts · {contracts?.total?offset+1:0}–{Math.min(offset+24,contracts?.total??0)}</span><div><button disabled={!offset} onClick={()=>setOffset(Math.max(0,offset-24))}>Previous</button><button disabled={offset+24>=(contracts?.total??0)} onClick={()=>setOffset(offset+24)}>Next</button></div></div>
      </section>{ticket&&<div className="selection-column"><div className="selection-tools"><Link className="text-link" href={`/charts/?instrument=${encodeURIComponent(ticket.id)}`}>Contract chart ↗</Link><button aria-label="Close contract ticket" onClick={()=>setTicket(null)}>×</button></div><TradeTicket key={ticket.id} instrument={ticket} quote={quotes[ticket.id]}/></div>}</div>
    </>:<div className="panel empty-state">Select an index above to explore its contracts.<small>Index levels are references; orders use a specific futures or options contract.</small></div>}
    <p className="fine-print">Only broker-listed indices and active contracts are shown. Index funds and ETFs are available through the Stocks page’s ETF filter.</p>
  </>
}
