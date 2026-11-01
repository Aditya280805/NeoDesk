import { useEffect, type JSX } from 'react'
import { X } from 'lucide-react'
import { useMarketStore } from '@/stores/marketStore'
import { useQuotes } from '@/lib/useQuotes'
import TradeTicket from '@/components/TradeTicket'

export default function OrderDrawer(): JSX.Element | null {
  const orderDrawer = useMarketStore((s) => s.orderDrawer)
  const closeOrderDrawer = useMarketStore((s) => s.closeOrderDrawer)

  const instrument = orderDrawer.instrument
  const { quotes } = useQuotes(instrument ? [instrument.id] : [])
  const quote = instrument ? quotes[instrument.id] : undefined

  useEffect(() => {
    if (!orderDrawer.isOpen) return

    const originalOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        closeOrderDrawer()
      }
    }

    window.addEventListener('keydown', handleKeyDown)

    return () => {
      document.body.style.overflow = originalOverflow
      window.removeEventListener('keydown', handleKeyDown)
    }
  }, [orderDrawer.isOpen, closeOrderDrawer])

  if (!orderDrawer.isOpen || !instrument) {
    return null
  }

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end"
      role="dialog"
      aria-modal="true"
      aria-label={`Order ticket for ${instrument.symbol}`}
    >
      {/* Backdrop overlay */}
      <div
        className="fixed inset-0 bg-black/60 backdrop-blur-sm transition-opacity"
        onClick={closeOrderDrawer}
        aria-hidden="true"
      />

      {/* Slide-over right edge panel */}
      <aside
        className="relative z-10 w-full max-w-md h-full bg-[#0E1624] border-l border-[#1D2C42] shadow-2xl flex flex-col overflow-y-auto animate-in slide-in-from-right duration-200"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Drawer header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-[#1D2C42] bg-[#070B12]/80 sticky top-0 z-20 backdrop-blur-md">
          <div className="flex items-center gap-2">
            <span className="font-semibold text-slate-100 text-sm">Quick Order</span>
            <span className="text-xs text-slate-400">· {instrument.symbol}</span>
          </div>
          <button
            type="button"
            onClick={closeOrderDrawer}
            className="p-1.5 rounded-lg text-slate-400 hover:text-slate-100 hover:bg-[#1D2C42] transition-colors"
            aria-label="Close order drawer"
          >
            <X size={18} />
          </button>
        </div>

        {/* Drawer content: TradeTicket */}
        <div className="p-4 flex-1">
          <TradeTicket
            key={`${instrument.id}-${orderDrawer.initialSide}`}
            instrument={instrument}
            quote={quote}
            initialSide={orderDrawer.initialSide}
          />
        </div>
      </aside>
    </div>
  )
}
