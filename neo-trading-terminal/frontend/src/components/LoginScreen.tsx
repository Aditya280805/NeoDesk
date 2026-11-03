import { FormEvent, useState } from 'react'
import Link from 'next/link'
import { ArrowRight, Check, Eye, EyeOff, KeyRound, ShieldCheck, Wallet, Sparkles } from 'lucide-react'
import { api, AuthResponse, failure, clearLegacyAuthToken, User } from '@/lib/api'

export default function LoginScreen({onSignedIn,checking=false,message=''}:{onSignedIn:(user:User,kotak:boolean,notice?:string)=>Promise<void>;checking?:boolean;message?:string}){
  const [mode,setMode]=useState<'kotak'|'signin'|'signup'>('signin')
  const [busy,setBusy]=useState(false),[error,setError]=useState(''),[visible,setVisible]=useState(false)
  const [email,setEmail]=useState('')
  const [password,setPassword]=useState('')
  const [displayName,setDisplayName]=useState('')

  async function submit(event:FormEvent<HTMLFormElement>){
    event.preventDefault()
    setBusy(true);setError('')
    try{
      // Broker credentials and session tokens are never saved in browser storage.
      clearLegacyAuthToken()
      if(mode==='kotak'){
        const form=event.currentTarget,data=Object.fromEntries(new FormData(form))
        const result=await api<{user:User;portfolio_sync_error:string|null}>('/auth/kotak-login','POST',data)
        form.reset()
        await onSignedIn(result.user,true,result.portfolio_sync_error??'')
      }else if(mode==='signup'){
        const result=await api<AuthResponse>('/auth/register','POST',{email,password,display_name:displayName})
        await onSignedIn(result.user,false)
      }else{
        const result=await api<AuthResponse>('/auth/login','POST',{email,password})
        await onSignedIn(result.user,false)
      }
    }catch(e){setError(failure(e))}finally{setBusy(false)}
  }

  function change(next:typeof mode){
    setMode(next)
    setError('')
  }

  function fillDemoCredentials(){
    setEmail('demo@neodesk.com')
    setPassword('DemoTrader123!')
    setError('')
  }

  return <main className="auth-page">
    <section className="auth-story"><Link className="brand" href="/"><span className="brand-mark">N</span>neo<span>desk</span></Link>
      <div className="auth-story-body"><span className="auth-eyebrow">YOUR INDIAN MARKET WORKSPACE</span><h1>One sign-in.<br/>Your whole portfolio.</h1><p>Bring your Kotak Neo holdings, positions and orders into one focused active trading workspace.</p>
        <div className="auth-benefit"><Wallet size={22}/><div><strong>Your portfolio, ready on arrival</strong><span>Holdings and account balances sync when you sign in.</span></div></div>
        <div className="auth-benefit"><KeyRound size={22}/><div><strong>A single connected session</strong><span>Explore stocks, futures and options without entering your details again.</span></div></div>
        <div className="auth-benefit"><ShieldCheck size={22}/><div><strong>A private workspace</strong><span>Your broker account and paper trading balance stay separate.</span></div></div>
      </div><small>Built for NSE & BSE · All amounts in INR</small>
    </section>
    <section className="auth-form-panel"><div className="auth-form-wrap">
      <div className="auth-tabs" role="tablist">
        <button type="button" className={`auth-tab ${mode!=='kotak'?'active':''}`} onClick={()=>change('signin')}>
          Paper Trading (Demo)
        </button>
        <button type="button" className={`auth-tab ${mode==='kotak'?'active':''}`} onClick={()=>change('kotak')}>
          Kotak Neo (Live Broker)
        </button>
      </div>

      <span className="auth-status"><span className="dot green"/>{mode==='kotak'?'KOTAK NEO CONNECTION':'NEODESK PRACTICE ACCOUNT'}</span>
      <h2>{mode==='kotak'?'Welcome to NeoDesk':mode==='signup'?'Create a practice account':'Welcome to NeoDesk Terminal'}</h2>
      <p className="auth-description">{mode==='kotak'?'Sign in once with your Kotak Trade API credentials to sync your live portfolio.': 'Sign in with your practice account to test the Kotak Neo active trader terminal.'}</p>

      {checking?<div className="auth-loading" role="status"><span className="spinner"/>Checking your session…</div>:<>
        {message&&<p className="auth-message" role="status">{message}</p>}

        {mode==='signin'&&<div className="auth-demo-badge" onClick={fillDemoCredentials} role="button" tabIndex={0}>
          <span><Sparkles size={14} style={{display:'inline',marginRight:6,verticalAlign:'text-bottom'}}/><strong>Demo Account:</strong> <code>demo@neodesk.com</code></span>
          <span style={{fontWeight:600,textDecoration:'underline'}}>Fill credentials</span>
        </div>}

        <form onSubmit={submit} key={mode}>
          <fieldset disabled={busy} className="auth-fields">
            {mode==='kotak'?<>
              <label htmlFor="consumer-key">Kotak API key<input id="consumer-key" name="consumer_key" type={visible?'text':'password'} maxLength={2048} required autoComplete="off" placeholder="Consumer key from Kotak Trade API"/><small>Find it in Kotak Neo → More → Trade API.</small></label>
              <div className="auth-form-row"><label htmlFor="client-code">Client code (UCC)<input id="client-code" name="ucc" required maxLength={30} pattern="[A-Za-z0-9]+" autoComplete="username" placeholder="Your Kotak client code"/></label><label htmlFor="broker-mobile">Registered mobile<input id="broker-mobile" name="mobile" type="tel" required pattern="\+[0-9]{10,15}" autoComplete="tel" placeholder="+919876543210"/></label></div>
              <div className="auth-form-row"><label htmlFor="broker-totp">Authenticator code (TOTP)<input id="broker-totp" name="totp" type="text" inputMode="numeric" required minLength={6} maxLength={6} pattern="[0-9]{6}" autoComplete="one-time-code" placeholder="6-digit current code"/></label><label htmlFor="broker-mpin">Kotak MPIN<input id="broker-mpin" name="mpin" type={visible?'text':'password'} inputMode="numeric" required minLength={6} maxLength={6} pattern="[0-9]{6}" autoComplete="off" placeholder="6-digit MPIN"/></label></div>
              <button className="auth-reveal" type="button" onClick={()=>setVisible(!visible)} aria-pressed={visible}>{visible?<EyeOff size={15}/>:<Eye size={15}/>} {visible?'Hide':'Show'} API key and MPIN</button>
            </>:<>
              {mode==='signup'&&<label>Your name<input name="display_name" value={displayName} onChange={e=>setDisplayName(e.target.value)} required autoComplete="name" placeholder="Aditya Bose"/></label>}
              <label>Email address<input name="email" type="email" value={email} onChange={e=>setEmail(e.target.value)} required autoComplete="email" placeholder="demo@neodesk.com"/></label>
              <label>Password<input name="password" type="password" value={password} onChange={e=>setPassword(e.target.value)} minLength={mode==='signup'?8:undefined} required autoComplete={mode==='signup'?'new-password':'current-password'} placeholder="••••••••"/></label>
            </>}
            {error&&<div className="error" role="alert">{error}</div>}
            <button className="primary auth-submit" type="submit">{busy?<><span className="spinner"/>{mode==='kotak'?'Verifying & syncing portfolio…':'Signing in…'}</>:<>{mode==='kotak'?'Sign in & open portfolio':mode==='signup'?'Create practice account':'Sign in'}<ArrowRight size={18}/></>}</button>
          </fieldset>
        </form>
        <p className="auth-privacy"><ShieldCheck size={16}/>{mode==='kotak'?'Your MPIN and TOTP are used only for this login and are never saved on the server.':'Your practice account starts with ₹1,00,000 virtual capital.'}</p>
        {mode==='kotak'?<><a className="auth-help" href="https://github.com/Kotak-Neo/kotak-neo-python/blob/main/docs/functions/authentication/totp_login.md" target="_blank" rel="noreferrer">First time? Set up Kotak TOTP ↗</a><div className="auth-alternative"><span>Just exploring?</span><button type="button" onClick={()=>change('signin')}>Use demo paper trading</button></div></>:<div className="auth-alternative"><button type="button" onClick={()=>change(mode==='signin'?'signup':'signin')}>{mode==='signin'?'Need a new account? Create one':'Already registered? Sign in'}</button><button type="button" onClick={()=>change('kotak')}>Sign in with Kotak Neo</button></div>}
      </>}
      <div className="auth-check"><Check size={14}/>Direct session connection</div>
    </div></section>
  </main>
}
