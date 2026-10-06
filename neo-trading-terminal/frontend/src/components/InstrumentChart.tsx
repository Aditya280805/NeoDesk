import { useEffect, useRef } from 'react'
import { AreaSeries, ColorType, createChart, UTCTimestamp } from 'lightweight-charts'
import type { History } from './PriceChart'

export default function InstrumentChart({data}:{data:History}) {
  const host=useRef<HTMLDivElement>(null)
  useEffect(()=>{
    if(!host.current)return
    const rising=(data.candles.at(-1)?.close??0)>=(data.candles[0]?.close??0)
    const color=rising?'#34c88a':'#ef786b'
    const chart=createChart(host.current,{autoSize:true,height:340,layout:{background:{type:ColorType.Solid,color:'#101418'},textColor:'#8d969f',attributionLogo:true},grid:{vertLines:{visible:false},horzLines:{color:'#30383d'}},rightPriceScale:{visible:false},leftPriceScale:{visible:true,borderVisible:false},timeScale:{borderVisible:false,timeVisible:data.interval!=='D'},localization:{locale:'en-IN',timeFormatter:(t:number)=>new Date(t*1000).toLocaleString('en-IN',{timeZone:'Asia/Kolkata'})},crosshair:{vertLine:{color:'#667480'},horzLine:{color:'#667480'}}})
    const series=chart.addSeries(AreaSeries,{lineColor:color,topColor:rising?'#27965f99':'#b8554d88',bottomColor:'#10141800',lineWidth:2,priceLineVisible:false,lastValueVisible:false})
    series.setData(data.candles.map(c=>({time:c.time as UTCTimestamp,value:c.close})))
    chart.timeScale().fitContent()
    return()=>chart.remove()
  },[data])
  return <div ref={host} className="instrument-area" aria-label="Historical price chart"/>
}
