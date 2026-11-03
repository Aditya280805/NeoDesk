import { useState } from 'react'
import { CheckCircle2, RefreshCw } from 'lucide-react'
import { api, failure } from '@/lib/api'
import { useTerminal } from '@/components/Layout'

export default function Connections(){
  const {status,refresh}=useTerminal(),[busy,setBusy]=useState(false),[error,setError]=useState('')
  async function sync(){setBusy(true);setError('');try{await api('/instruments/sync','POST');await refresh()}catch(e){setError(failure(e))}finally{setBusy(false)}}
  return <><div className="page-heading"><div><p className="eyebrow">ACCOUNT & DATA</p><h1>Connections<span className="accent">.</span></h1><p>Your Kotak connection is established when you sign in.</p></div></div>{error&&<p className="error" role="alert">{error}</p>}<div className="two-columns">
    <section className="panel padded"><CheckCircle2 size={24}/><h2>Kotak Neo account</h2><p>{status?.broker_authenticated?'Your broker session is connected. Holdings, positions and orders load automatically in Portfolio & orders.':'No active broker session. Sign out and use the Kotak login to connect your portfolio.'}</p><span className="badge">{status?.broker_authenticated?'CONNECTED':'PAPER ACCOUNT'}</span><p className="fine-print">To switch broker accounts, sign out from the sidebar and sign in again. TOTP and MPIN are not saved.</p></section>
    <section className="panel padded"><RefreshCw size={24}/><h2>Indian market catalogue</h2><p>Listings refresh automatically after login when the catalogue is out of date. Retry here if a stock or contract is missing.</p><div className="big-number">{status?.catalogue.total.toLocaleString('en-IN')??'—'}<small>instruments indexed</small></div><button className="primary" disabled={busy||status?.catalogue_sync.running||status?.market_data_source!=='kotak'} onClick={()=>void sync()}>{status?.catalogue_sync.running?'Updating listings…':'Refresh catalogue'}</button>{status?.catalogue_sync.error&&<p className="error">{status.catalogue_sync.error}</p>}<p className="fine-print">Last updated: {status?.catalogue.updated_at?new Date(status.catalogue.updated_at).toLocaleString('en-IN',{timeZone:'Asia/Kolkata'}):'Not yet synced'}. Coverage follows Kotak’s instrument files.</p></section>
  </div></>
}
