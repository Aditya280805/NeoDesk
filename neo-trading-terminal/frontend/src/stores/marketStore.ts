import { create } from 'zustand';
import type { Instrument } from '@/lib/api';

export interface Quote {
    token: string;
    ltp: number;
}

export interface Signal {
    action: 'BUY' | 'SELL';
    instrument_id: string;
    price: number;
    timestamp: string;
    strategy_id?: string;
    message?: string;
}

export interface RiskAlert {
    strategy_id?: string;
    message: string;
    level?: 'WARNING' | 'CRITICAL';
    timestamp?: string;
}

export interface OrderDrawerState {
    isOpen: boolean;
    instrument: Instrument | null;
    initialSide: 'BUY' | 'SELL';
}

interface MarketState {
    quotes: Record<string, {price:number;at:number}>;
    setQuote: (token: string, ltp: number, receivedAt:string) => void;
    connected: boolean;
    setConnected: (status: boolean) => void;
    tradingMode: 'PAPER' | 'LIVE';
    setTradingMode: (mode: 'PAPER' | 'LIVE') => void;
    signals: Signal[];
    addSignal: (signal: Signal) => void;
    riskAlerts: RiskAlert[];
    addRiskAlert: (alert: RiskAlert) => void;
    orderDrawer: OrderDrawerState;
    openOrderDrawer: (instrument: Instrument, side?: 'BUY' | 'SELL') => void;
    closeOrderDrawer: () => void;
}

export const useMarketStore = create<MarketState>((set) => ({
    quotes: {},
    setQuote: (token, ltp, receivedAt) => set((state) => ({
        quotes: {
            ...state.quotes,
            [token]: {price:ltp,at:Date.parse(receivedAt)}
        }
    })),
    connected: false,
    setConnected: (status) => set(state=>({ connected: status,quotes:status?state.quotes:{} })),
    tradingMode: 'PAPER',
    setTradingMode: (mode) => set({ tradingMode: mode }),
    signals: [],
    addSignal: (signal) => set(state => ({ signals: [signal, ...state.signals].slice(0, 50) })),
    riskAlerts: [],
    addRiskAlert: (alert) => set(state => ({ riskAlerts: [alert, ...state.riskAlerts].slice(0, 50) })),
    orderDrawer: {
        isOpen: false,
        instrument: null,
        initialSide: 'BUY'
    },
    openOrderDrawer: (instrument, side = 'BUY') => set({
        orderDrawer: {
            isOpen: true,
            instrument,
            initialSide: side
        }
    }),
    closeOrderDrawer: () => set((state) => ({
        orderDrawer: {
            ...state.orderDrawer,
            isOpen: false
        }
    }))
}));

export const useLiveQuote = (instrumentId: string | undefined): number | undefined => {
    return useMarketStore((state) => {
        const quote=instrumentId?state.quotes[instrumentId]:undefined;
        return quote && Date.now()-quote.at<10000 ? quote.price : undefined;
    });
};
