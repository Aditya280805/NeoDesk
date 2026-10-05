# NeoDesk — Indian market terminal

A connected Next.js frontend and FastAPI backend, with a persistent ₹1,00,000 paper account. Both can run at one local address and later on one Render Docker service.

## Implemented

- Searchable NSE/BSE instrument catalogue, exchange/type filters, sorting and watchlists.
- Dedicated Stocks and Indices & F&O pages, company/index search, active contracts, expiry/strike filters and shared paper order tickets.
- Activity cards ranked within a labelled tracked universe when broker volume is available; unranked featured examples otherwise.
- Kotak REST quote snapshots, historical candlesticks, SMA 20/50/200 and Wilder RSI 14.
- Option-chain view with expiries, premiums, volume and open interest.
- Paper market/limit orders, reserved cash/holdings, cancellations, average cost, realized/unrealized P&L and SQLite persistence.
- Separate Kotak connection and broker account-view pages; consumer-key verification and TOTP/MPIN login.
- Configurable long-only SMA strategy test with next-bar-open fills, fee/slippage assumptions and no lookahead.
- Single-user password protection for hosting; broker credentials stay server-side.

**Real-money order execution is disabled.** Live account means account viewing, not an enabled live order ticket. Futures paper trading supports market orders, long/short positions, partial closing and reversals, with an illustrative fixed 20% entry-value reserve—not Kotak/exchange margin. Unrealized losses do not reduce available cash in this simplified model; there is no liquidation or daily settlement. Options remain long-only. No TradingView alert receiver, streaming tick feed or realistic exchange matching is implemented. Paper fills use fetched LTP; fees, liquidity, partial fills and expiry settlement are not modeled. Demo and Kotak paper accounts cannot be mixed without an explicit reset.

## Run on this computer

From this project folder in PowerShell:

```powershell
.\run-local.ps1
```

Open [NeoDesk locally](http://127.0.0.1:8000). The script builds the frontend and starts the backend in the foreground. Stop with Ctrl+C. After an unchanged build, use `.\run-local.ps1 -SkipBuild`. If port 8000 is occupied, stop the previous server or use `-Port 8001`.

The backend environment already exists under `backend/.venv`. Paper data is stored in `data/terminal.sqlite3`; do not delete it to restart the app.

### Fresh installation

Install Node.js 24 and Python 3.12, then:

```powershell
cd frontend
npm ci
cd ..\backend
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
cd ..
.\run-local.ps1
```

For separate development servers, run `npm run dev` in frontend and `.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000` in backend. Use localhost:3000 for the frontend. The combined static mode is the deployment-equivalent check.

## Where to enter your Kotak key

Open **Connections → Kotak Neo market data → Consumer key → Connect & verify quotes**. Then **Sync complete catalogue**. Browser-entered credentials stay in backend memory and are lost on restart.

For restart persistence, copy `.env.example` to `.env` only if no `.env` already exists. Privately set `KOTAK_CONSUMER_KEY` and `MARKET_DATA_SOURCE=kotak`, then restart. Never use NEXT_PUBLIC variables for secrets. Rotate the key previously shared in chat before deployment.

The dashboard starts in clearly labelled demo mode unless a key is configured. The imported catalogue may still be real while its prices are synthetic; source labels distinguish these. For broker account viewing, complete TOTP/MPIN login in Connections. This has not been verified against your private account because those details were not supplied.

## Verification

```powershell
cd backend
.venv\Scripts\python.exe -m pytest -q
cd ..\frontend
npm run lint
npm run build
```

Tests cover account arithmetic, reservations, duplicate-order protection, source isolation, restart persistence, origin checks, password-protected APIs, broker response validation and historical batch boundaries. Build success does not establish broker account permissions or production readiness.

Read-only Kotak checks verified quotes and a 139,335-record catalogue on 1 October 2026. Short daily history and option-chain access also responded successfully. Catalogue availability and rate limits can interrupt later checks; errors remain visible rather than being replaced with sample prices. Longer history and authenticated account access require further live verification.

## Guides

- [Data coverage, TradingView, alternatives and details needed from you](docs/DATA_AND_TRADINGVIEW.md)
- [Prepared Render hosting instructions](docs/DEPLOY_RENDER.md)

Deployment remains on hold at your request. No repository or paid hosting service has been created.
