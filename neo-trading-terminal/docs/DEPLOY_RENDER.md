# Hosting later: one Render service

Deployment is deliberately on hold while the local project is evaluated. No repository, paid service or public deployment has been created.

The root Dockerfile builds the Next.js static frontend and serves it through FastAPI. Both use the same HTTPS origin; there is no second frontend service and no production NEXT_PUBLIC_API_URL to configure.

## When ready

1. Create a separate private GitHub repository for this terminal, not the Kotak SDK fork. Commit the contents of `neo-trading-terminal`, excluding `.env`, `data`, logs, `.venv`, `node_modules`, `.next` and `out`.
2. In Render, create a Blueprint from that repository using `render.yaml`. Review the paid Starter service and 1 GB persistent-disk costs before approving creation. The configuration is prepared but has not been deployed or Docker-built here.
3. The Blueprint generates `APP_PASSWORD`. Retrieve it privately in Render's environment settings and use it to sign into your website. Never share it in chat.
4. To retain broker connectivity across restarts, privately add `KOTAK_CONSUMER_KEY` and change `MARKET_DATA_SOURCE` to `kotak`. Alternatively, use Connections after each restart; that key stays only in server memory.
5. Keep `ENVIRONMENT=production`, `DATA_DIR=/var/data`, one instance, one worker, and live execution disabled. Set `FRONTEND_URL` to the exact HTTPS site origin if you use a custom domain. Render's standard external URL is accepted automatically.
6. Check `/api/health`, then sign in, sync the catalogue, verify source labels and make only a paper test trade. Restart and confirm paper holdings survive.

## Persistence and operating limits

- SQLite lives at `/var/data/terminal.sqlite3`. A free/ephemeral filesystem is not suitable for preserving the account. Keep backups; copy SQLite using its backup API or stop the service before copying the database and WAL files.
- Browser sessions and broker sessions are memory-only and expire on restart. Paper records and watchlists persist on the disk.
- This is one personal account, not a multi-user brokerage platform. Do not share the password or publish broker data for others without checking data-redistribution rights.
- The API never sends broker credentials back to the frontend. MPIN/TOTP are not persisted. Rotate any key previously shared in chat before hosting.
- Real-money order placement, streaming ticks, TradingView alert ingestion and futures margin simulation are not implemented. `LIVE_TRADING_ENABLED=true` does not unlock order execution.

References: [Render web services](https://render.com/docs/web-services), [persistent disks](https://render.com/docs/disks), [Blueprint specification](https://render.com/docs/blueprint-spec).
