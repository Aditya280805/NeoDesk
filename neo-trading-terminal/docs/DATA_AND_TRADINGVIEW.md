# Data, indicators and strategy integration

## Current data source

The application uses the official `kotakneoapi==3.0.7` package. Your GitHub fork contains the broker SDK; the dashboard, persistence, paper ledger, authentication and indicator calculations are application code built around it. No YFinance is used.

Connect the consumer key in **Connections**, then sync all four supported segments: NSE cash, BSE cash, NSE F&O and BSE F&O. Search/sort the resulting catalogue; not every record is a stock. It also includes derivatives, debt and other broker instruments. Instruments can be unavailable, illiquid, suspended or expired despite appearing in a master file.

The successful import on 1 October 2026 contained 139,335 records. Discovery identifies NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY, NIFTYNXT50, SENSEX, BANKEX and SENSEX50 from spot entries and derivative underlyings. NIFTYNXT50 has contracts but no spot quote entry in that import. This is broker-file coverage, **not a claim that every Indian sectoral or broad-market index is included**. Counts change daily. Failed refreshes retain the previous catalogue.

## Stocks and index discovery

Stocks searches cash shares and ETFs separately from derivatives, with exchange filters, watchlists, sorting and pagination. Indices & F&O searches index names and aliases, then lists active futures or options by expiry, call/put and strike. Contract dates and lot sizes come from the broker catalogue; expired contracts are excluded from new orders. An index itself is not a buyable share.

Activity cards compare selected NSE shares, or the nearest available future for each discovered index. They are not market-wide most-traded rankings. Volume and estimated traded value (volume × VWAP) use broker snapshots, refreshed on demand with a one-minute cache. Missing activity falls back to explicitly unranked featured examples.

Futures paper orders use a fixed illustrative 20% reserve on entry value and support long/short market orders, partial closes and reversals. This is not a broker margin calculator: no SPAN/exposure margin, daily settlement, liquidation or automatic expiry settlement. Unrealized losses do not reduce available cash. Stock selling closes owned shares; option selling closes long options. No naked option writing or real-money execution is enabled.

Markets refresh REST snapshots every five seconds while open. This is not a streaming tick feed. Closed markets show the last available price, not a newly traded price. Demo prices are visibly synthetic; a failed Kotak request never falls back silently to demo prices.

Daily chart requests are split into inclusive 180-calendar-day batches. Indicators include SMA 20, 50 and 200 plus Wilder RSI 14. SMA 200 requires at least 200 valid daily closes. Intraday SMA uses the selected candle interval. Corporate-action adjustments are not verified, and the latest candle may be incomplete. Rate limits and broker permissions still apply.

## TradingView

When only part of the requested history is available, the chart displays the available candles with an explicit warning. The strategy tester refuses incomplete history so missing batches cannot silently produce a misleading backtest. No missing candles are synthesized.

The embedded chart uses open-source Lightweight Charts with data and indicators supplied by this backend. It does not include Pine Script or TradingView's Strategy Tester.

Use your Pine strategy on tradingview.com to run TradingView's own tests. The local Strategy lab currently tests a configurable long-only moving-average regime: prior-close signal, next-bar-open execution, illustrative fee/slippage inputs and mark-to-market of final holdings. It is not an arbitrary Python/Pine strategy execution service. These results are research examples, not reliable predictions of trading performance.

Webhook alerts could be added as a separate, authenticated paper-only integration. That would need request validation, replay protection, deduplication, an explicit instrument mapping and audit records. No alert receiver or real-money automation is enabled now.

Official references: [Kotak SDK](https://github.com/Kotak-Neo/kotak-neo-python), [historical data](https://github.com/Kotak-Neo/kotak-neo-python/blob/main/docs/functions/market_data/historical_data.md), [TradingView library FAQ](https://www.tradingview.com/charting-library-docs/latest/resources/Frequently-Asked-Questions/), [webhook alerts](https://www.tradingview.com/support/solutions/43000529348-how-to-configure-webhook-alerts/).

## Alternatives

Kotak is the practical first integration because you already have access. If its coverage or history is insufficient, official alternatives include [Upstox market data](https://upstox.com/developer/api-documentation/get-full-market-quote-v3/) and [Dhan live feeds](https://dhanhq.co/docs/v2/live-market-feed/). Each requires its own account/access and permission checks; neither is integrated here. Exchange-authorized data vendors are another route if you need broader index/history coverage or redistribution rights.

## What is needed from you next

- Your Pine code or precise strategy rules: entries, exits, timeframe, universe, risk limits, position sizing and costs.
- Which indices are essential beyond the eight currently discovered, and how far back you need history.
- Your intended paper-trading behavior for expiry, realistic futures margin, option writing, fees and market hours; the simulator deliberately excludes those advanced models.
- For account-view testing, enter your UCC, registered mobile, current TOTP and MPIN privately in Connections. Do not send them in chat.
- For eventual hosting, a separate source repository and Render account. No Aadhaar, PAN, bank statements or other KYC documents are needed by this application.
