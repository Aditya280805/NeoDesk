import { create } from 'zustand';

export interface Quote {
    token: string;
    ltp: number;
}

interface MarketState {
    quotes: Record<string, number>;
    setQuote: (token: string, ltp: number) => void;
    connected: boolean;
    setConnected: (status: boolean) => void;
    tradingMode: 'PAPER' | 'LIVE';
    setTradingMode: (mode: 'PAPER' | 'LIVE') => void;
}

export const useMarketStore = create<MarketState>((set) => ({
    quotes: {},
    setQuote: (token, ltp) => set((state) => ({
        quotes: {
            ...state.quotes,
            [token]: ltp
        }
    })),
    connected: false,
    setConnected: (status) => set({ connected: status }),
    tradingMode: 'PAPER',
    setTradingMode: (mode) => set({ tradingMode: mode }),
}));

export const useLiveQuote = (instrumentId: string | undefined): number | undefined => {
    return useMarketStore((state) => instrumentId ? state.quotes[instrumentId] : undefined);
};
