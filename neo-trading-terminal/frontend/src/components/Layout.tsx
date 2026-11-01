import Head from 'next/head'
import Link from 'next/link'
import { useRouter } from 'next/router'
import { createContext, ReactNode, useContext, useEffect, useRef, useState } from 'react'
import { Activity, BarChart3, CandlestickChart, FlaskConical, Link2, LogOut, Wallet, Moon, Sun, MessageCircle } from 'lucide-react'
import { api, failure, clearLegacyAuthToken, Status, User } from '@/lib/api'
import { useMarketStore } from '@/stores/marketStore'
import { useTheme } from 'next-themes'
import LoginScreen from './LoginScreen'
import { wsService } from '@/services/ws'
import IndexTickerStrip from '@/components/IndexTickerStrip'
import OrderDrawer from '@/components/OrderDrawer'

const Terminal=createContext<{status:Status|null;refresh:()=>Promise<void>;user:User|null}>({status:null,refresh:async()=>{},user:null})
export const useTerminal=()=>useContext(Terminal)
const routes=[['/','Overview',BarChart3],['/stocks/','Stocks',BarChart3],['/indices/','Indices & F&O',Activity],['/charts/','Charts',CandlestickChart],['/options/','Option chain',Activity],['/options-chat/','Options chat',MessageCircle],['/trading/','Portfolio & orders',Wallet],['/strategies/','Strategy lab',FlaskConical],['/connections/','Connections',Link2]] as const

export default function Layout({children}:{children:ReactNode}){
  const router=useRouter(),{tradingMode,setTradingMode}=useMarketStore(),{resolvedTheme:theme,setTheme}=useTheme()
  const [mounted,setMounted]=useState(false),[session,setSession]=useState<boolean|null>(null),[user,setUser]=useState<User|null>(null)
  const [status,setStatus]=useState<Status|null>(null),[error,setError]=useState(''),[loginMessage,setLoginMessage]=useState('')
  const restored=useRef(false)
  const [stopBusy,setStopBusy]=useState(false)
  async function refresh(){setStatus(await api<Status>('/status'))}
  async function toggleOrders(){
    setStopBusy(true)
    try{await api(status?.orders_stopped?'/risk/reset-kill-switch':'/risk/kill-switch','POST');await refresh();setError('')}
    catch(e){setError(failure(e))}finally{setStopBusy(false)}
  }
  useEffect(()=>{
    let active=true,running=false
    const read=async()=>{
      if(running)return
      running=true
      try{
        const s=await api<{authenticated:boolean;user?:User}>('/session')
        if(!active)return
        setMounted(true)
        if(!s.authenticated||!s.user){setSession(false);setUser(null);return}
        const next=await api<Status>('/status')
        if(!active)return
        if(s.user.email.endsWith('@broker.invalid')&&!next.broker_authenticated){
          setSession(false);setLoginMessage('Your Kotak session has expired. Sign in to reconnect your portfolio.');return
        }
        setUser(s.user);setStatus(next);setSession(true)
        if(!restored.current){setTradingMode(s.user.email.endsWith('@broker.invalid')?'LIVE':'PAPER');restored.current=true}
      }catch(e){if(active){setMounted(true);setSession(false);setLoginMessage(failure(e))}}finally{running=false}
    }
    const expired=()=>{if(active){setSession(false);setUser(null);setLoginMessage('Your session has expired. Please sign in again.')}}
    window.addEventListener('neodesk:session-expired',expired)
    void read();const timer=setInterval(read,15000)
    return()=>{active=false;clearInterval(timer);window.removeEventListener('neodesk:session-expired',expired)}
  },[setTradingMode])
  useEffect(()=>{
    if(session===true)wsService.connect()
    else wsService.disconnect()
    return()=>wsService.disconnect()
  },[session,user?.id])
  async function signedIn(next:User,kotak:boolean,notice=''){
    clearLegacyAuthToken();setUser(next);setLoginMessage('');setError(notice)
    restored.current=true
    useMarketStore.setState({quotes:{},signals:[],riskAlerts:[]})
    setTradingMode(kotak?'LIVE':'PAPER')
    await refresh();setSession(true)
    await router.replace('/trading/')
  }
  async function logout(){
    try{await api('/auth/logout','POST')}catch(e){setError(failure(e));return}
    clearLegacyAuthToken();setSession(false);setUser(null);setStatus(null);setTradingMode('PAPER');setError('')
    restored.current=false
    useMarketStore.setState({quotes:{},signals:[],riskAlerts:[]});wsService.disconnect()
    await router.replace('/login/')
  }
  const isLogin=router.pathname==='/login'
  useEffect(()=>{if(session===true&&isLogin)void router.replace('/trading/')},[session,isLogin,router])
  const brokerUser=user?.email.endsWith('@broker.invalid')
  const name=user?.display_name||'Your workspace'
  const initials=brokerUser?'KN':name.trim().split(/\s+/).map(n=>n[0]).join('').slice(0,2).toUpperCase()
  return <Terminal.Provider value={{status,refresh,user}}><Head><title>{session===true?'NeoDesk · Indian markets':'Sign in · NeoDesk'}</title><meta name="description" content="Connect your Kotak Neo portfolio, explore Indian markets and manage your trades."/></Head>
    {session!==true?<LoginScreen onSignedIn={signedIn} checking={session===null} message={loginMessage}/>:<div className="app-shell">
      <aside className="sidebar">
        <Link className="brand" href="/">
          <span className="brand-mark">N</span>
          neo<span className="brand-accent">desk</span>
          <span className="kotak-neo-badge">Neo</span>
        </Link>
        <div className="nav-label">YOUR WORKSPACE</div>
        <nav>
          {routes.map(([url,label,Icon])=><Link key={url} href={url} className={(router.pathname+'/'===url||router.pathname===url)?'selected':''}><Icon size={18}/>{label}</Link>)}
        </nav>
        <div className="sidebar-bottom">
          <div className="account-avatar">{initials}</div>
          <div><b>{name}</b><small>{brokerUser?'Kotak Neo account':user?.email}</small></div>
          <button className="icon-button" aria-label="Sign out" title="Sign out" onClick={logout}><LogOut size={16}/></button>
        </div>
      </aside>
      <div className="workspace">
        <header className={`topbar ${tradingMode==='LIVE'?'live-mode':''}`}>
          <div className="topbar-status">
            <span className={`dot ${status?.market_data_source==='kotak'?'green':'amber'}`}/>
            {status?.market_data_source==='kotak'?(status.market_error?'Kotak · quotes unavailable':'Kotak · connected'):'Paper workspace'}
            <span className="top-separator">/</span>
            <span className="muted">NSE & BSE</span>
          </div>
          <div className="ticker-bar">
            <IndexTickerStrip />
          </div>
          <div className="topbar-actions">
            {mounted&&<button className="icon-button" aria-label="Toggle Theme" onClick={()=>setTheme(theme==='dark'?'light':'dark')}>{theme==='dark'?<Sun size={18}/>:<Moon size={18}/>}</button>}
            {tradingMode==='LIVE'&&<button className="danger" onClick={toggleOrders} disabled={stopBusy}>{stopBusy?'Updating…':status?.orders_stopped?'Resume orders':'Stop orders'}</button>}
            <div className="mode-pills">
              <button onClick={()=>setTradingMode('PAPER')} className={tradingMode==='PAPER'?'selected':''}>Paper</button>
              <button onClick={()=>setTradingMode('LIVE')} className={`live-btn ${tradingMode==='LIVE'?'selected':''}`}>Kotak account</button>
            </div>
          </div>
        </header>
        <div className="mobile-account"><span>{name}</span><button onClick={logout}><LogOut size={14}/>Sign out</button></div>
        <main className="page-content" key={user?.id}>{error&&<p className="error" role="alert">{error}</p>}{status?.market_data_source==='demo'&&<div className="demo-banner">Paper prices are synthetic. <button onClick={()=>{setSession(false);setLoginMessage('Sign in with Kotak to connect your real portfolio.')}}>Sign in with Kotak Neo</button></div>}{tradingMode==='LIVE'&&<div className="broker-mode-banner">Kotak account · {status?.live_trading_enabled?'Orders submitted here use your real broker account.':'Portfolio viewing is active. Live orders are disabled on this server.'}</div>}{children}</main>
        <footer>NeoDesk / Your trading workspace <span>Kotak Neo · Times shown in IST</span></footer>
      </div>
      <OrderDrawer />
    </div>}
  </Terminal.Provider>
}
