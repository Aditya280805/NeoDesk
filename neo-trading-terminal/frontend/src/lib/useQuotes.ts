import { useEffect, useState } from 'react'
import { api, failure, Quote } from './api'
import { useTerminal } from '@/components/Layout'

export function useQuotes(ids:string[]):{quotes:Record<string,Quote>;error:string;updatedAt:string} {
  const {status}=useTerminal()
  const key=Array.from(new Set(ids)).slice(0,50).sort().join(',')
  const source=status?.market_data_source??''
  const stateKey=`${source}:${key}`
  const [state,setState]=useState<{key:string;quotes:Record<string,Quote>;error:string;updatedAt:string}>({key:'',quotes:{},error:'',updatedAt:''})
  useEffect(()=>{
    if(!source)return
    let active=true,running=false
    async function load(force=false){
      if(running)return
      if(!force&&typeof document!=='undefined'&&document.visibilityState==='hidden')return
      running=true
      try{
        const rows=key?await api<Quote[]>('/market/quotes','POST',{ids:key.split(',')}):[]
        const stamp=key&&rows.length?new Date().toLocaleTimeString('en-IN',{timeZone:'Asia/Kolkata'}):''
        if(active)setState({key:stateKey,quotes:Object.fromEntries(rows.map(q=>[q.id,q])),error:key&&!rows.length?'No quote was returned for this instrument. Check the broker connection or try again shortly.':'',updatedAt:stamp})
      }catch(e){if(active)setState({key:stateKey,quotes:{},error:failure(e),updatedAt:''})}
      finally{running=false}
    }
    void load(true)
    const timer=setInterval(()=>{void load()},5000)
    const onVisibility=()=>{if(typeof document!=='undefined'&&document.visibilityState==='visible')void load(true)}
    if(typeof document!=='undefined')document.addEventListener('visibilitychange',onVisibility)
    return()=>{
      active=false
      clearInterval(timer)
      if(typeof document!=='undefined')document.removeEventListener('visibilitychange',onVisibility)
    }
  },[key,stateKey,source])
  return state.key===stateKey?state:{quotes:{},error:'',updatedAt:''}
}
