import Link from 'next/link'
import { ArrowUpRight, Search, Star } from 'lucide-react'
import { Instrument, money, Quote } from '@/lib/api'
import { companyName, exchangeName, kindName } from '@/lib/instruments'
import { useMarketStore } from '@/stores/marketStore'
import CompanyLabel from './CompanyLabel'

export default function MarketTable({items,quotes,watch,onWatch,loading=false}:{items:Instrument[];quotes:Record<string,Quote>;watch:Instrument[];onWatch:(i:Instrument)=>void;loading?:boolean}){
  const openOrderDrawer = useMarketStore(s => s.openOrderDrawer)

  return (
    <div className="market-table-wrap" aria-busy={loading}>
      <table className="market-table">
        <thead>
          <tr>
            <th><span className="sr-only">Watchlist</span></th>
            <th>Company</th>
            <th>Market</th>
            <th className="numeric">Last price</th>
            <th className="numeric">Change</th>
            <th><span className="sr-only">Actions</span></th>
          </tr>
        </thead>
        <tbody>
          {loading ? (
            Array.from({length: 5}, (_, n) => (
              <tr key={n} className="market-skeleton">
                <td colSpan={6}><span/></td>
              </tr>
            ))
          ) : (
            items.map(i => {
              const quote = quotes[i.id]
              const saved = watch.some(w => w.id === i.id)
              return (
                <tr key={i.id}>
                  <td className="watch-cell">
                    <button
                      className={`star ${saved ? 'on' : ''}`}
                      aria-label={`${saved ? 'Remove' : 'Add'} ${companyName(i)} ${saved ? 'from' : 'to'} watchlist`}
                      aria-pressed={saved}
                      onClick={() => onWatch(i)}
                    >
                      <Star size={16}/>
                    </button>
                  </td>
                  <td>
                    <Link className="company-link" href={`/instrument/?instrument=${encodeURIComponent(i.id)}`}>
                      <CompanyLabel instrument={i}/>
                    </Link>
                  </td>
                  <td>
                    <span className="market-exchange">{exchangeName(i.exchange)}</span>
                    <small className="market-kind">{kindName(i.kind)}</small>
                  </td>
                  <td className="numeric market-price">{money(quote?.ltp)}</td>
                  <td className="numeric">
                    <span
                      className={`market-change ${quote ? (quote.change_pct > 0 ? 'positive bg-emerald-500/10 text-[#00D09C]' : quote.change_pct < 0 ? 'negative bg-red-500/10 text-[#FF4757]' : 'muted') : 'muted'}`}
                    >
                      {quote ? `${quote.change_pct > 0 ? '+' : ''}${quote.change_pct.toFixed(2)}%` : '—'}
                    </span>
                  </td>
                  <td>
                    <div className="market-actions-wrap">
                      <button
                        type="button"
                        className="quick-btn quick-buy"
                        aria-label={`Buy ${companyName(i)}`}
                        onClick={() => openOrderDrawer(i, 'BUY')}
                      >
                        B
                      </button>
                      <button
                        type="button"
                        className="quick-btn quick-sell"
                        aria-label={`Sell ${companyName(i)}`}
                        onClick={() => openOrderDrawer(i, 'SELL')}
                      >
                        S
                      </button>
                      <Link
                        className="market-open"
                        aria-label={`View ${companyName(i)}`}
                        href={`/instrument/?instrument=${encodeURIComponent(i.id)}`}
                      >
                        <ArrowUpRight size={15}/>
                      </Link>
                    </div>
                  </td>
                </tr>
              )
            })
          )}
        </tbody>
      </table>
      {!loading && !items.length && (
        <div className="market-empty">
          <Search size={25}/>
          <h3>No companies found</h3>
          <p>Try another company name, symbol or exchange.</p>
        </div>
      )}
    </div>
  )
}
