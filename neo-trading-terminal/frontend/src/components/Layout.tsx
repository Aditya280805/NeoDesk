import Head from 'next/head'
import Link from 'next/link'
import { useRouter } from 'next/router'
import { createContext, FormEvent, ReactNode, useContext, useEffect, useState } from 'react'
import { Activity, BarChart3, BookOpen, CandlestickChart, FlaskConical, Link2, LogOut, Wallet, Moon, Sun } from 'lucide-react'
import { api, failure, Status } from '@/lib/api'
import { useMarketStore } from '@/stores/marketStore'
import { useTheme } from 'next-themes'

const Terminal = createContext<{status:Status|null;refresh:()=>Promise<void>}>({status:null,refresh:async()=>{}})
export const useTerminal = () => useContext(Terminal)

const routes = [ ['/', 'Overview', BarChart3], ['/stocks/','Stocks',BarChart3], ['/indices/','Indices & F&O',Activity], ['/charts/','Charts',CandlestickChart], ['/options/','Option chain',Activity],
  ['/trading/','Trading Dashboard',Wallet], ['/strategies/','Strategy lab',FlaskConical], ['/connections/','Connections',Link2] ] as const

export default function Layout({children}:{children:ReactNode}) {
  const router=useRouter()
  const { tradingMode, setTradingMode } = useMarketStore()
  const { theme, setTheme } = useTheme()
  const [mounted, setMounted] = useState(false)
  const [session,setSession]=useState<boolean|null>(null)
  const [status,setStatus]=useState<Status|null>(null)
  const [error,setError]=useState('')
  async function refresh() { setStatus(await api<Status>('/status')) }
  useEffect(()=>{
    let cancelled=false
    const read=async()=>{
      try {
        const s=await api<{authenticated:boolean}>('/session')
        if(cancelled)return
        setMounted(true)
        setSession(s.authenticated)
        if(s.authenticated){const next=await api<Status>('/status');if(!cancelled)setStatus(next)}
        if(!cancelled)setError('')
      }catch(e){if(!cancelled)setError(failure(e))}
    }
    void read(); const timer=setInterval(read,10000)
    return ()=>{cancelled=true;clearInterval(timer)}
  },[])
  async function login(event:FormEvent<HTMLFormElement>){
    event.preventDefault(); const form=event.currentTarget
    try {await api('/login','POST',{password:new FormData(form).get('password')});form.reset();setSession(true);await refresh();setError('')}
    catch(e){setError(failure(e))}
  }
  return <Terminal.Provider value={{status,refresh}}><Head><title>NeoDesk · Indian markets</title><meta name="description" content="Indian markets, charts and a personal paper trading terminal"/></Head>
    {session!==true ? <div className="login-screen"><div className="login-card"><span className="brand-mark">N</span><h1>Your market workspace.</h1><p>Sign in to your personal NeoDesk terminal.</p>{session===false && <form onSubmit={login}><label>Terminal password<input name="password" type="password" autoComplete="current-password" required/></label><button className="primary">Sign in</button></form>}{session===null&&<p>Connecting to your backend…</p>}{error&&<p className="error" role="alert">{error}</p>}</div></div> : <div className="app-shell">
      <aside className="sidebar"><Link className="brand" href="/"><span className="brand-mark">N</span>neo<span>desk</span></Link><div className="nav-label">YOUR WORKSPACE</div><nav>{routes.map(([url,label,Icon])=><Link key={url} href={url} className={(router.pathname+'/'===url||router.pathname===url)?'selected':''}><Icon size={18}/>{label}</Link>)}</nav><div className="sidebar-bottom"><div className="account-avatar">AB</div><div><b>Personal terminal</b><small>India · INR</small></div><button className="icon-button" aria-label="Sign out" onClick={async()=>{await api('/logout','POST');setSession(false)}}><LogOut size={16}/></button></div></aside>
      <div className="workspace"><header className={`topbar ${tradingMode === 'LIVE' ? 'live-mode' : ''}`}><div><span className={`dot ${status?.market_data_source==='kotak'?'green':'amber'}`}/>{status?.market_data_source==='kotak'?(status.market_error?'Kotak · quotes unavailable':'Kotak · 5s snapshots'):'Demo market data'}<span className="top-separator">/</span><span className="muted">NSE & BSE</span></div><div style={{ display: 'flex', alignItems: 'center', gap: '15px' }}>{mounted && <button className="icon-button" aria-label="Toggle Theme" onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')} style={{ color: 'var(--muted)' }}>{theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}</button>}{tradingMode === 'LIVE' && <button className="danger" onClick={async () => { await api('/risk/kill-switch', 'POST') }}>KILL SWITCH</button>}<div className="mode-pills"><button onClick={() => setTradingMode('PAPER')} className={tradingMode==='PAPER'?'selected':''}>Paper</button><button onClick={() => setTradingMode('LIVE')} className={`live-btn ${tradingMode==='LIVE'?'selected':''}`}>Live account</button></div></div></header>
      <main className="page-content">{error&&<p className="error" role="alert">{error}</p>}{status?.market_data_source==='demo'&&<div className="demo-banner">Demo prices are synthetic. <Link href="/connections/">Connect Kotak Neo</Link> to use broker market data.</div>}{tradingMode==='LIVE'&&<div className="demo-banner" style={{background: '#ffe5e5', color: '#c62828', border: '1px solid #ffcdd2'}}>⚠️ REAL MONEY AT RISK: LIVE TRADING MODE IS ACTIVE. ⚠️</div>}{children}</main>
      <footer>NeoDesk / Personal trading workspace <span>Exchange data: Kotak Neo · Times shown in IST</span></footer></div></div>}
  </Terminal.Provider>
}
