import { useEffect, useRef } from 'react'
import { useTheme } from 'next-themes'
import { CandlestickSeries, ColorType, createChart, LineSeries, UTCTimestamp } from 'lightweight-charts'
export type Candle = {time:number;open:number;high:number;low:number;close:number;volume:number}
export type History = {partial?:boolean;candles:Candle[];source:string;interval:string;note:string;indicators:{sma20:(number|null)[];sma50:(number|null)[];sma200:(number|null)[];rsi14:(number|null)[]}}
export default function PriceChart({data, instrumentId}:{data:History, instrumentId?: string}){
  const container=useRef<HTMLDivElement>(null)
  const {resolvedTheme}=useTheme()

  useEffect(()=>{
    if(!container.current)return
    const light=resolvedTheme==='light',grid=light?'#e2e8f0':'#1c2a37'
    const up=light?'#047857':'#53d8b0',down=light?'#b91c1c':'#f28387'
    const chart=createChart(container.current,{autoSize:true,height:440,layout:{background:{type:ColorType.Solid,color:light?'#ffffff':'#101923'},textColor:light?'#526176':'#8da1b6',attributionLogo:true},grid:{vertLines:{color:grid},horzLines:{color:grid}},timeScale:{timeVisible:data.interval!=='D'},localization:{timeFormatter:(t:number)=>new Date(t*1000).toLocaleString('en-IN',{timeZone:'Asia/Kolkata'})}})
    const series=chart.addSeries(CandlestickSeries,{upColor:up,downColor:down,borderVisible:false,wickUpColor:up,wickDownColor:down})
    series.setData(data.candles.map(c=>({...c,time:c.time as UTCTimestamp})))
    ;(['sma20','sma50','sma200'] as const).forEach((key,n)=>{const line=chart.addSeries(LineSeries,{color:(light?['#92400e','#1d4ed8','#7e22ce']:['#f0c674','#77aafa','#c49af5'])[n],lineWidth:1,title:key.toUpperCase()});line.setData(data.candles.flatMap((c,i)=>data.indicators[key][i]==null?[]:[{time:c.time as UTCTimestamp,value:data.indicators[key][i]!}]))})
    const rsi=chart.addSeries(LineSeries,{color:light?'#7e22ce':'#c49af5',lineWidth:1,title:'RSI 14'},1)
    rsi.setData(data.candles.flatMap((c,i)=>data.indicators.rsi14[i]==null?[]:[{time:c.time as UTCTimestamp,value:data.indicators.rsi14[i]!}]))
    rsi.createPriceLine({price:70,color:'#76444b',lineWidth:1,lineStyle:2,axisLabelVisible:true,title:'70'})
    rsi.createPriceLine({price:30,color:'#376556',lineWidth:1,lineStyle:2,axisLabelVisible:true,title:'30'})
    chart.timeScale().fitContent()
    return()=>{
      chart.remove()
    }
  },[data,resolvedTheme])

  return <><div ref={container} className="price-chart"/><div className="chart-credit">Charts by <a href="https://www.tradingview.com/" target="_blank" rel="noreferrer">TradingView Lightweight Charts™</a> · <span className="gold">SMA 20</span> · <span className="blue">SMA 50</span> · SMA 200 · RSI 14</div></>
}
