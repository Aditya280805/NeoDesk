import { useEffect, useState } from 'react'
import { api, failure, Quote } from './api'
import { useTerminal } from '@/components/Layout'

export function useQuotes(ids:string[]):{quotes:Record<string,Quote>;error:string} {
  const {status}=useTerminal()
  const key=Array.from(new Set(ids)).slice(0,50).sort().join(',')
  const source=status?.market_data_source??''
  const stateKey=`${source}:${key}`
  const [state,setState]=useState<{key:string;quotes:Record<string,Quote>;error:string}>({key:'',quotes:{},error:''})
  useEffect(()=>{
    if(!source)return
    let active=true,running=false
    async function load(){
      if(running)return
      running=true
      try{
        const rows=key?await api<Quote[]>('/market/quotes','POST',{ids:key.split(',')}):[]
        if(active)setState({key:stateKey,quotes:Object.fromEntries(rows.map(q=>[q.id,q])),error:key&&!rows.length?'No quote was returned for this instrument. Check the broker connection or try again shortly.':''})
      }catch(e){if(active)setState({key:stateKey,quotes:{},error:failure(e)})}
      finally{running=false}
    }
    void load();const timer=setInterval(load,5000)
    return()=>{active=false;clearInterval(timer)}
  },[key,stateKey,source])
  return state.key===stateKey?state:{quotes:{},error:''}
}
