# Kotak Neo Active Trader Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Overhaul NeoDesk's frontend into Kotak Neo's high-speed active trader layout with a dark navy palette, persistent multi-index ticker, quick B/S order drawer, and unified high-density trading desk.

**Architecture:** Next.js pages router with React 19 and Tailwind CSS. A global `IndexTickerStrip` and `OrderDrawer` mount directly inside `Layout.tsx`, wired into `useMarketStore` for instant drawer triggers across all views. CSS variables in `globals.css` and `market.css` provide the Kotak Neo dark navy aesthetic, while `trading.tsx` and `MarketTable.tsx` receive ergonomic trader upgrades.

**Tech Stack:** Next.js 16.4, React 19.3, Tailwind CSS 3.4, Zustand 4.5, Lucide-react, lightweight-charts.

**Spec:** `neo-trading-terminal/docs/superpowers/specs/2026-10-30-kotak-neo-active-trader-layout-design.md`

## Global Constraints
- Must maintain full compatibility with existing backend REST and WebSocket APIs without altering backend code.
- Must preserve Next.js 16 / React 19 compilation and pass `npm run build` and `npm test` without regressions.
- Supported order execution types remain `MARKET` and `LIMIT` (preventing HTTP 422 errors).
- Dark theme tokens must adhere strictly to Kotak Neo dark navy values: base `#070B12`, surface `#0E1624`, line `#1D2C42`, green `#00D09C`, red `#FF4757`, blue `#2563EB`.

## Review Focus
- Drawer unmount/cleanup: closing the slide-over drawer via backdrop click, `Esc` key, or close button cleans up state without lingering background scroll locks.
- Ticker empty or delayed quotes: if `/indices` or `/market/quotes` are slow or return empty, `IndexTickerStrip` displays stable shimmer/placeholders without crashing or shifting layout.
- Rapid B/S clicks: clicking Buy or Sell rapidly on different rows correctly swaps the drawer's active instrument and side without race conditions or multiple open drawers.
- Square-Off side inversion: squaring off a short position (negative quantity) pre-fills a `BUY` order, while squaring off a long position (positive quantity) pre-fills a `SELL` order with positive absolute quantity.
- Responsive collapsing: on viewports < 768px, top ticker becomes horizontally scrollable and drawer covers 100% width with accessible tap targets.

---

### Task 1: Kotak Neo Design Tokens & Theme Foundation

**Files:**
- Modify: `neo-trading-terminal/frontend/src/styles/globals.css:11-37`
- Modify: `neo-trading-terminal/frontend/src/styles/market.css:1-12`
- Test: `neo-trading-terminal/frontend/tests/theme-tokens.test.cjs`

**Interfaces:**
- Consumes: CSS root variables `--bg`, `--panel`, `--panel-hover`, `--line`, `--text`, `--muted`, `--green`, `--red`, `--accent`, `--accent-dim`
- Produces: Updated CSS variable values for dark mode (`#070B12`, `#0E1624`, `#1D2C42`, `#00D09C`, `#FF4757`, `#2563EB`), updated metric gradient styles, button styles, card borders.

- [ ] **Step 1: Write the failing test**
Create `neo-trading-terminal/frontend/tests/theme-tokens.test.cjs`:
```javascript
const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')

test('dark theme tokens match Kotak Neo palette', () => {
  const css = fs.readFileSync(path.join(__dirname, '../src/styles/globals.css'), 'utf8')
  assert.match(css, /--bg:\s*#070b12/i, 'dark bg must match Kotak Neo deep navy')
  assert.match(css, /--panel:\s*#0e1624/i, 'dark panel must match Kotak Neo surface')
  assert.match(css, /--line:\s*#1d2c42/i, 'dark line must match Kotak Neo border')
  assert.match(css, /--green:\s*#00d09c/i, 'dark green must match Kotak Neo vibrant emerald')
  assert.match(css, /--red:\s*#ff4757/i, 'dark red must match Kotak Neo coral red')
})
```

- [ ] **Step 2: Run test to verify it fails**
Run: `cmd /c "cd neo-trading-terminal\frontend && node --test tests/theme-tokens.test.cjs"`
Expected: FAIL with assertion error.

- [ ] **Step 3: Implement new theme tokens in `globals.css` and `market.css`**
Update `.dark` block in `src/styles/globals.css` with the exact Kotak Neo color values, card gradients, and active state styles. Update `src/styles/market.css` surface and soft variables to match.

- [ ] **Step 4: Run test to verify it passes**
Run: `cmd /c "cd neo-trading-terminal\frontend && node --test tests/theme-tokens.test.cjs"`
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add neo-trading-terminal/frontend/src/styles/globals.css neo-trading-terminal/frontend/src/styles/market.css neo-trading-terminal/frontend/tests/theme-tokens.test.cjs
git commit -m "feat(theme): apply Kotak Neo dark navy palette and design tokens"
```

---

### Task 2: Persistent Multi-Index Ticker Strip Component

**Files:**
- Create: `neo-trading-terminal/frontend/src/components/IndexTickerStrip.tsx`
- Test: `neo-trading-terminal/frontend/tests/index-ticker.test.cjs`

**Interfaces:**
- Consumes: `api<IndexItem[]>('/indices')`, `api<Quote[]>('/market/quotes', 'POST', { ids })`, `money` from `@/lib/api`
- Produces: `export default function IndexTickerStrip(): JSX.Element` rendering NIFTY 50, SENSEX, and BANK NIFTY chips with live updates.

- [ ] **Step 1: Write the failing test**
Create `neo-trading-terminal/frontend/tests/index-ticker.test.cjs`:
```javascript
const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')

test('IndexTickerStrip source defines index mapping and polling interval', () => {
  const filePath = path.join(__dirname, '../src/components/IndexTickerStrip.tsx')
  assert.ok(fs.existsSync(filePath), 'IndexTickerStrip.tsx must exist')
  const content = fs.readFileSync(filePath, 'utf8')
  assert.match(content, /NIFTY 50|SENSEX/i, 'IndexTickerStrip must target key Indian indices')
  assert.match(content, /setInterval/i, 'IndexTickerStrip must set polling interval')
})
```

- [ ] **Step 2: Run test to verify it fails**
Run: `cmd /c "cd neo-trading-terminal\frontend && node --test tests/index-ticker.test.cjs"`
Expected: FAIL (file does not exist).

- [ ] **Step 3: Implement `IndexTickerStrip.tsx`**
Create `src/components/IndexTickerStrip.tsx`:
- Fetch `/indices` on mount to resolve `spot.id`s for Nifty 50, Sensex, and Bank Nifty.
- Query `/market/quotes` periodically (5s) for live updates.
- Render horizontal strip of ticker chips showing name, LTP, change, and % with flashing color classes.

- [ ] **Step 4: Run test to verify it passes**
Run: `cmd /c "cd neo-trading-terminal\frontend && node --test tests/index-ticker.test.cjs"`
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add neo-trading-terminal/frontend/src/components/IndexTickerStrip.tsx neo-trading-terminal/frontend/tests/index-ticker.test.cjs
git commit -m "feat(ticker): add persistent multi-index ticker strip"
```

---

### Task 3: Global Order Drawer Store & Component

**Files:**
- Modify: `neo-trading-terminal/frontend/src/stores/marketStore.ts`
- Create: `neo-trading-terminal/frontend/src/components/OrderDrawer.tsx`
- Test: `neo-trading-terminal/frontend/tests/order-drawer.test.cjs`

**Interfaces:**
- Consumes: `useMarketStore`
- Produces:
  - In `marketStore.ts`: `orderDrawer: { isOpen: boolean; instrument: Instrument | null; initialSide: 'BUY' | 'SELL' }`, `openOrderDrawer(instrument: Instrument, side?: 'BUY' | 'SELL'): void`, `closeOrderDrawer(): void`
  - In `OrderDrawer.tsx`: `export default function OrderDrawer(): JSX.Element | null` mounting slide-over drawer with `TradeTicket`.

- [ ] **Step 1: Write the failing test**
Create `neo-trading-terminal/frontend/tests/order-drawer.test.cjs`:
```javascript
const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')

test('OrderDrawer component and store integration exists', () => {
  const storeContent = fs.readFileSync(path.join(__dirname, '../src/stores/marketStore.ts'), 'utf8')
  assert.match(storeContent, /orderDrawer/i, 'marketStore must include orderDrawer state')
  assert.match(storeContent, /openOrderDrawer/i, 'marketStore must include openOrderDrawer action')
  
  const drawerPath = path.join(__dirname, '../src/components/OrderDrawer.tsx')
  assert.ok(fs.existsSync(drawerPath), 'OrderDrawer.tsx must exist')
  const drawerContent = fs.readFileSync(drawerPath, 'utf8')
  assert.match(drawerContent, /TradeTicket/i, 'OrderDrawer must embed TradeTicket')
})
```

- [ ] **Step 2: Run test to verify it fails**
Run: `cmd /c "cd neo-trading-terminal\frontend && node --test tests/order-drawer.test.cjs"`
Expected: FAIL.

- [ ] **Step 3: Implement `orderDrawer` store slice and `OrderDrawer.tsx`**
Update `src/stores/marketStore.ts` with `orderDrawer` state and actions. Create `src/components/OrderDrawer.tsx` with slide-over right panel, backdrop overlay, Esc key listener, and `TradeTicket` embedding.

- [ ] **Step 4: Run test to verify it passes**
Run: `cmd /c "cd neo-trading-terminal\frontend && node --test tests/order-drawer.test.cjs"`
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add neo-trading-terminal/frontend/src/stores/marketStore.ts neo-trading-terminal/frontend/src/components/OrderDrawer.tsx neo-trading-terminal/frontend/tests/order-drawer.test.cjs
git commit -m "feat(drawer): add global slide-over order drawer"
```

---

### Task 4: Watchlist Row Quick Action Triggers (B / S) & MarketTable Redesign

**Files:**
- Modify: `neo-trading-terminal/frontend/src/components/MarketTable.tsx`
- Modify: `neo-trading-terminal/frontend/src/styles/market.css`
- Test: `neo-trading-terminal/frontend/tests/watchlist-actions.test.cjs`

**Interfaces:**
- Consumes: `useMarketStore(s => s.openOrderDrawer)`
- Produces: Quick **B** and **S** buttons on `MarketTable` rows, compact 36px–40px row height, colored percentage badges.

- [ ] **Step 1: Write the failing test**
Create `neo-trading-terminal/frontend/tests/watchlist-actions.test.cjs`:
```javascript
const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')

test('MarketTable contains quick buy and sell action buttons', () => {
  const content = fs.readFileSync(path.join(__dirname, '../src/components/MarketTable.tsx'), 'utf8')
  assert.match(content, /openOrderDrawer/i, 'MarketTable must use openOrderDrawer')
  assert.match(content, /quick-buy|quick-btn/i, 'MarketTable must render quick action buttons')
})
```

- [ ] **Step 2: Run test to verify it fails**
Run: `cmd /c "cd neo-trading-terminal\frontend && node --test tests/watchlist-actions.test.cjs"`
Expected: FAIL.

- [ ] **Step 3: Implement quick B/S buttons and styling in `MarketTable.tsx` and `market.css`**
Add hover actions on row with **B** button (`BUY`) and **S** button (`SELL`) triggering `openOrderDrawer(instrument, side)`. Adjust row height to 38px and add change percentage badge styling.

- [ ] **Step 4: Run test to verify it passes**
Run: `cmd /c "cd neo-trading-terminal\frontend && node --test tests/watchlist-actions.test.cjs"`
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add neo-trading-terminal/frontend/src/components/MarketTable.tsx neo-trading-terminal/frontend/src/styles/market.css neo-trading-terminal/frontend/tests/watchlist-actions.test.cjs
git commit -m "feat(watchlist): add quick Buy/Sell action buttons and compact row styling"
```

---

### Task 5: Topbar & Shell Integration in `Layout.tsx`

**Files:**
- Modify: `neo-trading-terminal/frontend/src/components/Layout.tsx`
- Modify: `neo-trading-terminal/frontend/src/styles/globals.css`
- Test: `neo-trading-terminal/frontend/tests/layout-shell.test.cjs`

**Interfaces:**
- Consumes: `IndexTickerStrip`, `OrderDrawer`
- Produces: Integrated topbar with ticker strip, global drawer container, and modern active trader sidebar.

- [ ] **Step 1: Write the failing test**
Create `neo-trading-terminal/frontend/tests/layout-shell.test.cjs`:
```javascript
const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')

test('Layout mounts IndexTickerStrip and OrderDrawer', () => {
  const content = fs.readFileSync(path.join(__dirname, '../src/components/Layout.tsx'), 'utf8')
  assert.match(content, /IndexTickerStrip/i, 'Layout must mount IndexTickerStrip')
  assert.match(content, /OrderDrawer/i, 'Layout must mount OrderDrawer')
})
```

- [ ] **Step 2: Run test to verify it fails**
Run: `cmd /c "cd neo-trading-terminal\frontend && node --test tests/layout-shell.test.cjs"`
Expected: FAIL.

- [ ] **Step 3: Integrate ticker and drawer in `Layout.tsx` and polish sidebar styling**
Import `IndexTickerStrip` and place in workspace header. Mount `OrderDrawer` inside the layout shell. Restyle navigation items with active left indicator bar and modern Kotak Neo branding badge.

- [ ] **Step 4: Run test to verify it passes**
Run: `cmd /c "cd neo-trading-terminal\frontend && node --test tests/layout-shell.test.cjs"`
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add neo-trading-terminal/frontend/src/components/Layout.tsx neo-trading-terminal/frontend/src/styles/globals.css neo-trading-terminal/frontend/tests/layout-shell.test.cjs
git commit -m "feat(layout): integrate persistent index ticker and order drawer into AppShell"
```

---

### Task 6: Trading Workstation Redesign & One-Click Square-Off in `trading.tsx`

**Files:**
- Modify: `neo-trading-terminal/frontend/src/pages/trading.tsx`
- Modify: `neo-trading-terminal/frontend/src/components/TradeTicket.tsx`
- Modify: `neo-trading-terminal/frontend/src/components/BrokerPortfolio.tsx`
- Test: `neo-trading-terminal/frontend/tests/trading-workstation.test.cjs`

**Interfaces:**
- Consumes: `TradeTicket`, `BrokerPortfolio`
- Produces: Positions table with "Square Off" action button pre-filling inverse order, product tags (`MIS`, `CNC`, `NRML`) on ticket, and live P&L metrics cards.

- [ ] **Step 1: Write the failing test**
Create `neo-trading-terminal/frontend/tests/trading-workstation.test.cjs`:
```javascript
const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')

test('trading page and TradeTicket support square-off and product tabs', () => {
  const ticketContent = fs.readFileSync(path.join(__dirname, '../src/components/TradeTicket.tsx'), 'utf8')
  assert.match(ticketContent, /MIS|CNC|NRML/i, 'TradeTicket must display product tabs')
  
  const tradingContent = fs.readFileSync(path.join(__dirname, '../src/pages/trading.tsx'), 'utf8')
  assert.match(tradingContent, /Square off|square-off/i, 'trading page must render square off button')
})
```

- [ ] **Step 2: Run test to verify it fails**
Run: `cmd /c "cd neo-trading-terminal\frontend && node --test tests/trading-workstation.test.cjs"`
Expected: FAIL.

- [ ] **Step 3: Implement square-off handler and TradeTicket enhancements**
In `trading.tsx` and `BrokerPortfolio.tsx`, implement square-off logic that loads the position into `instrument`, sets opposite side (`BUY`/`SELL`) and net quantity into `TradeTicket`. In `TradeTicket.tsx`, add product selector tabs and lot size quick stepper buttons.

- [ ] **Step 4: Run test to verify it passes**
Run: `cmd /c "cd neo-trading-terminal\frontend && node --test tests/trading-workstation.test.cjs"`
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add neo-trading-terminal/frontend/src/pages/trading.tsx neo-trading-terminal/frontend/src/components/TradeTicket.tsx neo-trading-terminal/frontend/src/components/BrokerPortfolio.tsx neo-trading-terminal/frontend/tests/trading-workstation.test.cjs
git commit -m "feat(trading): implement position square-off and enhance TradeTicket"
```

---

### Task 7: End-to-End Regression Verification & Production Build

**Files:**
- Test: All tests in `tests/*.test.cjs`
- Build: Next.js production build

- [ ] **Step 1: Run all unit test suites**
Run: `cmd /c "cd neo-trading-terminal\frontend && npm test"`
Expected: All tests pass with 0 failures.

- [ ] **Step 2: Run full production build**
Run: `cmd /c "cd neo-trading-terminal\frontend && npm run build"`
Expected: `✓ Compiled successfully`, all static pages generated without TypeScript or ESLint errors.

- [ ] **Step 3: Final Commit**
```bash
git commit --allow-empty -m "chore: verify Kotak Neo active trader layout implementation"
```
