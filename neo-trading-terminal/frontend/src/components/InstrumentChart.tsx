import { useEffect, useRef } from 'react'
import { useTheme } from 'next-themes'
import { AreaSeries, ColorType, createChart, UTCTimestamp } from 'lightweight-charts'
import type { History } from './PriceChart'

export default function InstrumentChart({data}:{data:History}) {
  const host=useRef<HTMLDivElement>(null)
  const {resolvedTheme}=useTheme()
  useEffect(()=>{
    if(!host.current)return
    const rising=(data.candles.at(-1)?.close??0)>=(data.candles[0]?.close??0)
    const light=resolvedTheme==='light'
    const color=rising?(light?'#047857':'#34c88a'):(light?'#b91c1c':'#ef786b')
    const chart=createChart(host.current,{autoSize:true,height:340,layout:{background:{type:ColorType.Solid,color:light?'#ffffff':'#101418'},textColor:light?'#526176':'#8d969f',attributionLogo:true},grid:{vertLines:{visible:false},horzLines:{color:light?'#e2e8f0':'#30383d'}},rightPriceScale:{visible:false},leftPriceScale:{visible:true,borderVisible:false},timeScale:{borderVisible:false,timeVisible:data.interval!=='D'},localization:{locale:'en-IN',timeFormatter:(t:number)=>new Date(t*1000).toLocaleString('en-IN',{timeZone:'Asia/Kolkata'})},crosshair:{vertLine:{color:'#667480'},horzLine:{color:'#667480'}}})
    const series=chart.addSeries(AreaSeries,{lineColor:color,topColor:rising?'#27965f99':'#b8554d88',bottomColor:'#10141800',lineWidth:2,priceLineVisible:false,lastValueVisible:false})
    series.setData(data.candles.map(c=>({time:c.time as UTCTimestamp,value:c.close})))
    chart.timeScale().fitContent()
    return()=>chart.remove()
  },[data,resolvedTheme])
  return <div ref={host} className="instrument-area" aria-label="Historical price chart"/>
}
