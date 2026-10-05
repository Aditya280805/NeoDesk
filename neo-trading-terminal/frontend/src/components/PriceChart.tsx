import { useEffect, useRef } from 'react'
import { CandlestickSeries, ColorType, createChart, LineSeries, UTCTimestamp, ISeriesApi } from 'lightweight-charts'
import { useLiveQuote } from '@/stores/marketStore'
export type Candle = {time:number;open:number;high:number;low:number;close:number;volume:number}
export type History = {partial?:boolean;candles:Candle[];source:string;interval:string;note:string;indicators:{sma20:(number|null)[];sma50:(number|null)[];sma200:(number|null)[];rsi14:(number|null)[]}}
export default function PriceChart({data, instrumentId}:{data:History, instrumentId?: string}){
  const container=useRef<HTMLDivElement>(null)
  const seriesRef=useRef<ISeriesApi<"Candlestick"> | null>(null)
  const liveQuote = useLiveQuote(instrumentId?.split('|')[1] || instrumentId)

  useEffect(()=>{
    if(!container.current)return
    const chart=createChart(container.current,{autoSize:true,height:440,layout:{background:{type:ColorType.Solid,color:'#101923'},textColor:'#8da1b6',attributionLogo:true},grid:{vertLines:{color:'#1c2a37'},horzLines:{color:'#1c2a37'}},timeScale:{timeVisible:data.interval!=='D'},localization:{timeFormatter:(t:number)=>new Date(t*1000).toLocaleString('en-IN',{timeZone:'Asia/Kolkata'})}})
    const series=chart.addSeries(CandlestickSeries,{upColor:'#53d8b0',downColor:'#f28387',borderVisible:false,wickUpColor:'#53d8b0',wickDownColor:'#f28387'})
    series.setData(data.candles.map(c=>({...c,time:c.time as UTCTimestamp})))
    ;(['sma20','sma50','sma200'] as const).forEach((key,n)=>{const line=chart.addSeries(LineSeries,{color:['#f0c674','#77aafa','#c49af5'][n],lineWidth:1,title:key.toUpperCase()});line.setData(data.candles.flatMap((c,i)=>data.indicators[key][i]==null?[]:[{time:c.time as UTCTimestamp,value:data.indicators[key][i]!}]))})
    const rsi=chart.addSeries(LineSeries,{color:'#c49af5',lineWidth:1,title:'RSI 14'},1)
    rsi.setData(data.candles.flatMap((c,i)=>data.indicators.rsi14[i]==null?[]:[{time:c.time as UTCTimestamp,value:data.indicators.rsi14[i]!}]))
    rsi.createPriceLine({price:70,color:'#76444b',lineWidth:1,lineStyle:2,axisLabelVisible:true,title:'70'})
    rsi.createPriceLine({price:30,color:'#376556',lineWidth:1,lineStyle:2,axisLabelVisible:true,title:'30'})
    chart.timeScale().fitContent()
    seriesRef.current = series
    return()=>{
      seriesRef.current = null
      chart.remove()
    }
  },[data])

  useEffect(()=>{
    if (liveQuote && seriesRef.current && data.candles.length > 0) {
      const last = data.candles[data.candles.length - 1]
      seriesRef.current.update({
        time: last.time as UTCTimestamp,
        open: last.open,
        high: Math.max(last.high, liveQuote),
        low: Math.min(last.low, liveQuote),
        close: liveQuote,
      })
    }
  }, [liveQuote, data])

  return <><div ref={container} className="price-chart"/><div className="chart-credit">Charts by <a href="https://www.tradingview.com/" target="_blank" rel="noreferrer">TradingView Lightweight Charts™</a> · <span className="gold">SMA 20</span> · <span className="blue">SMA 50</span> · SMA 200 · RSI 14</div></>
}
