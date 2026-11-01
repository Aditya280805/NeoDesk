import Link from 'next/link'
import { useEffect, useRef, useState, type JSX } from 'react'
import { api, money, Quote, Instrument } from '@/lib/api'
import { useTerminal } from '@/components/Layout'

type IndexItem = {
  id: string
  symbol: string
  name: string
  exchange: string
  spot: Instrument | null
  options_count: number
  futures_count: number
}

interface TargetIndex {
  key: string
  displayName: string
  match: (item: IndexItem) => boolean
}

const TARGET_INDICES: TargetIndex[] = [
  {
    key: 'NIFTY 50',
    displayName: 'NIFTY 50',
    match: (i) => i.symbol === 'NIFTY' || i.name.toLowerCase().includes('nifty 50') || i.symbol === 'NIFTY 50',
  },
  {
    key: 'SENSEX',
    displayName: 'SENSEX',
    match: (i) => i.symbol === 'SENSEX' || i.name.toLowerCase().includes('sensex'),
  },
  {
    key: 'BANK NIFTY',
    displayName: 'BANK NIFTY',
    match: (i) => i.symbol === 'BANKNIFTY' || i.name.toLowerCase().includes('bank') || i.symbol === 'NIFTY BANK',
  },
  {
    key: 'FINNIFTY',
    displayName: 'FINNIFTY',
    match: (i) => i.symbol === 'FINNIFTY' || i.name.toLowerCase().includes('financial services'),
  },
]

interface ResolvedIndex {
  key: string
  displayName: string
  spotId: string | null
}

function formatPointChange(q: Quote): { diffText: string; pctText: string; isPositive: boolean } {
  const isPositive = (q.change_pct ?? 0) >= 0
  const sign = isPositive ? '+' : ''
  let diff = 0
  if (q.ohlc?.close && q.ohlc.close > 0) {
    diff = q.ltp - q.ohlc.close
  } else if (q.change_pct !== undefined && q.change_pct !== null) {
    const close = q.ltp / (1 + q.change_pct / 100)
    diff = q.ltp - close
  }
  const diffStr = Math.abs(diff) < 0.005 ? '0.00' : `${sign}${diff.toFixed(2)}`
  const pctStr = `${sign}${(q.change_pct ?? 0).toFixed(2)}%`
  return {
    diffText: diffStr,
    pctText: pctStr,
    isPositive,
  }
}

export default function IndexTickerStrip(): JSX.Element {
  const { status } = useTerminal()
  const [indices, setIndices] = useState<ResolvedIndex[]>([])
  const [quotes, setQuotes] = useState<Record<string, Quote>>({})
  const [tickAnimations, setTickAnimations] = useState<Record<string, 'up' | 'down'>>({})
  const prevPricesRef = useRef<Record<string, number>>({})

  // Fetch /indices on mount or catalogue update to resolve spot IDs
  useEffect(() => {
    let active = true
    api<IndexItem[]>('/indices')
      .then((data) => {
        if (!active) return
        const resolved: ResolvedIndex[] = []
        for (const target of TARGET_INDICES) {
          const found = data.find(target.match)
          if (found) {
            resolved.push({
              key: target.key,
              displayName: target.displayName,
              spotId: found.spot?.id || found.id || null,
            })
          }
        }
        if (resolved.length > 0) {
          setIndices(resolved)
        }
      })
      .catch(() => {
        // Gracefully ignore fetch errors
      })
    return () => {
      active = false
    }
  }, [status?.catalogue?.updated_at])

  // Extract resolved spot IDs for market quote queries
  const spotIds = indices.map((idx) => idx.spotId).filter((id): id is string => Boolean(id))
  const spotIdsKey = spotIds.slice().sort().join(',')

  // Periodically poll /market/quotes every 5 seconds for live updates
  useEffect(() => {
    if (!spotIdsKey) return
    let active = true
    const idsToFetch = spotIdsKey.split(',')

    async function pollQuotes() {
      try {
        const rows = await api<Quote[]>('/market/quotes', 'POST', { ids: idsToFetch })
        if (!active) return

        const quotesMap: Record<string, Quote> = {}
        const newTicks: Record<string, 'up' | 'down'> = {}
        let hasTick = false

        for (const q of rows) {
          quotesMap[q.id] = q
          const prevPrice = prevPricesRef.current[q.id]
          if (prevPrice !== undefined && q.ltp !== prevPrice) {
            newTicks[q.id] = q.ltp > prevPrice ? 'up' : 'down'
            hasTick = true
          }
          prevPricesRef.current[q.id] = q.ltp
        }

        setQuotes((prev) => ({ ...prev, ...quotesMap }))

        if (hasTick) {
          setTickAnimations((prev) => ({ ...prev, ...newTicks }))
          setTimeout(() => {
            if (!active) return
            setTickAnimations((prev) => {
              const next = { ...prev }
              for (const k of Object.keys(newTicks)) {
                delete next[k]
              }
              return next
            })
          }, 1000)
        }
      } catch {
        // Gracefully ignore periodic polling errors
      }
    }

    void pollQuotes()
    const interval = setInterval(pollQuotes, 5000)
    return () => {
      active = false
      clearInterval(interval)
    }
  }, [spotIdsKey, status?.market_data_source])

  // Default placeholders prevent layout shift before indices load
  const displayIndices: ResolvedIndex[] =
    indices.length > 0
      ? indices
      : [
          { key: 'NIFTY 50', displayName: 'NIFTY 50', spotId: null },
          { key: 'SENSEX', displayName: 'SENSEX', spotId: null },
          { key: 'BANK NIFTY', displayName: 'BANK NIFTY', spotId: null },
        ]

  return (
    <div
      className="w-full overflow-x-auto flex items-center gap-2 py-1 px-1 scrollbar-none"
      role="region"
      aria-label="Market Indices Ticker"
    >
      {displayIndices.map((idx) => {
        const q = idx.spotId ? quotes[idx.spotId] : undefined
        const tick = idx.spotId ? tickAnimations[idx.spotId] : null
        const tickClass = tick === 'up' ? 'live-tick' : tick === 'down' ? 'negative live-tick' : ''
        const change = q ? formatPointChange(q) : null

        const chipContent = (
          <div className="flex items-center gap-2.5 px-3 py-1.5 rounded-lg bg-[#0E1624] border border-[#1D2C42] hover:border-[#2563EB]/60 hover:bg-[#152033] transition-colors shrink-0 cursor-pointer select-none">
            <span className="text-[11px] font-semibold tracking-wider text-slate-300 uppercase">
              {idx.displayName}
            </span>
            <span className={`font-mono text-xs font-bold tabular-nums text-slate-100 ${tickClass}`}>
              {money(q?.ltp)}
            </span>
            {change ? (
              <span
                className={`text-[11px] font-medium font-mono tabular-nums ${
                  change.isPositive ? 'positive text-[#00D09C]' : 'negative text-[#FF4757]'
                }`}
              >
                {change.diffText} ({change.pctText})
              </span>
            ) : (
              <span className="text-[11px] font-mono text-slate-500 tabular-nums">—</span>
            )}
          </div>
        )

        if (idx.spotId) {
          return (
            <Link
              key={idx.key}
              href={`/instrument/?instrument=${encodeURIComponent(idx.spotId)}`}
              className="no-underline shrink-0"
              title={`View ${idx.displayName} details`}
            >
              {chipContent}
            </Link>
          )
        }

        return (
          <div key={idx.key} className="shrink-0">
            {chipContent}
          </div>
        )
      })}
    </div>
  )
}
