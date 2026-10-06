import { create } from 'zustand';

export interface Quote {
    token: string;
    ltp: number;
}

interface MarketState {
    quotes: Record<string, {price:number;at:number}>;
    setQuote: (token: string, ltp: number, receivedAt:string) => void;
    connected: boolean;
    setConnected: (status: boolean) => void;
    tradingMode: 'PAPER' | 'LIVE';
    setTradingMode: (mode: 'PAPER' | 'LIVE') => void;
    signals: any[];
    addSignal: (signal: any) => void;
    riskAlerts: any[];
    addRiskAlert: (alert: any) => void;
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
}));

export const useLiveQuote = (instrumentId: string | undefined): number | undefined => {
    return useMarketStore((state) => {
        const quote=instrumentId?state.quotes[instrumentId]:undefined;
        return quote && Date.now()-quote.at<10000 ? quote.price : undefined;
    });
};
