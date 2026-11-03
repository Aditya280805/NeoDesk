import { apiBase } from '@/lib/api';
import { useMarketStore } from '@/stores/marketStore';

class WebSocketService {
    private ws: WebSocket | null = null;
    private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    private isIntentionallyClosed = false;

    private getWsUrl() {
        const base = apiBase();
        if (base) {
            return base.replace(/^http/, 'ws') + '/api/ws/stream';
        }
        if (typeof window !== 'undefined') {
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            return `${protocol}//${window.location.host}/api/ws/stream`;
        }
        return '';
    }

    connect() {
        if (typeof window === 'undefined') return; // Do not run on SSR
        if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
            return;
        }

        const url = this.getWsUrl();
        if (!url) return;

        this.isIntentionallyClosed = false;
        const socket = new WebSocket(url);
        this.ws = socket;

        this.ws.onopen = () => {
            if (this.ws !== socket) return;
            useMarketStore.getState().setConnected(true);
            if (this.reconnectTimer) {
                clearTimeout(this.reconnectTimer);
                this.reconnectTimer = null;
            }
        };

        this.ws.onmessage = (event) => {
            if (this.ws !== socket) return;
            try {
                const message = JSON.parse(event.data);
                if (message.type === 'QUOTE' && message.data) {
                    if(message.data.id && Number.isFinite(message.data.ltp) && message.data.ltp>0 && message.data.received_at)
                        useMarketStore.getState().setQuote(message.data.id, message.data.ltp, message.data.received_at);
                } else if (message.type === 'SIGNAL' && message.data) {
                    useMarketStore.getState().addSignal(message.data);
                } else if (message.type === 'RISK_ALERT' && message.data) {
                    useMarketStore.getState().addRiskAlert(message.data);
                }
            } catch (err) {
                console.error("WebSocket message parsing error:", err);
            }
        };

        this.ws.onclose = () => {
            if (this.ws !== socket) return;
            useMarketStore.getState().setConnected(false);
            this.ws = null;
            this.attemptReconnect();
        };

        this.ws.onerror = () => {
            // Error handling, closing the socket will trigger onclose and reconnect
            socket.close();
        };
    }

    private attemptReconnect() {
        if (this.isIntentionallyClosed) return;
        
        if (!this.reconnectTimer) {
            this.reconnectTimer = setTimeout(() => {
                this.reconnectTimer = null;
                this.connect();
            }, 3000);
        }
    }

    disconnect() {
        this.isIntentionallyClosed = true;
        useMarketStore.getState().setConnected(false);
        if (this.reconnectTimer) {
            clearTimeout(this.reconnectTimer);
            this.reconnectTimer = null;
        }
        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }
    }
}

export const wsService = new WebSocketService();
