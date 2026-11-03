# Design Document: Kotak Neo High-Speed Active Trader Layout

**Date:** 2026-10-30  
**Status:** Approved for Implementation Planning  
**Author:** Antigravity / Aditya Bose  
**Target:** `neo-trading-terminal/frontend`  

---

## 1. Intent and the Why

NeoDesk currently functions as a robust paper and live trading platform for Indian markets (NSE & BSE) connected to Kotak Neo. However, its visual interface currently resembles a dense, utilitarian monochrome terminal (pitch-black background, basic table lists, minimal hierarchy, no persistent index tracking).

The goal of this project is to overhaul the frontend look and feel into **Kotak Neo's high-speed active trader layout**. Kotak Neo is designed for speed, high visual feedback, and ergonomic information density. An active trader needs:
- Instant market sentiment at a glance (persistent multi-index ticker with flashing real-time quotes).
- Rapid execution capability (one-click buy/sell triggers directly from watchlists and positions).
- Deep navy, high-contrast visual ergonomics reducing eye strain during market hours.
- Clear structural division between market discovery, active order tickets, and portfolio exposure.

---

## 2. Goals, Non-Goals, and Anti-Goals

### Goals
1. **Kotak Neo Color Palette & Visual Elevation**:
   - Dark theme transition from pitch black (`#050505`) to Kotak Neo deep navy (`#070B12` base, `#0F1726` surface, `#162032` hover, `#1F2D44` crisp borders).
   - High-contrast, vibrant financial indicators: emerald gain (`#05D588`), coral red loss (`#FF4D6D`), Kotak electric blue (`#2563EB`).
   - Clean, rounded modern card geometry (8px–12px radii), subtle glow states for active modes, and refined typography.
2. **Persistent Multi-Index Ticker Bar**:
   - Place a persistent, real-time index strip in the global header displaying key Indian benchmarks (NIFTY 50, SENSEX, BANK NIFTY, FINNIFTY).
   - Show LTP, absolute point change, percentage change, and real-time tick pulse animations (`flash-green` / `flash-red`).
3. **Ergonomic Active Trader Shell**:
   - Modernized sidebar with refined active states, clean icon pairing, and seamless Live vs. Paper workspace indicators.
   - Prominent, color-coded broker status badge and instant emergency kill-switch ("Stop orders").
4. **Enhanced Watchlist & Slide-Over Quick Order Drawer**:
   - Tabbed watchlist controls (Watchlist 1–5, Indices, F&O).
   - Instant hover action triggers on stock rows: **B** (Buy in blue) and **S** (Sell in red) opening a smooth slide-over Order Drawer right over the current page (without losing search/watchlist context).
5. **Unified High-Density Trading Desk (`/trading/`)**:
   - Workstation layout: Left/Center holds Positions & Order Book with live P&L summary cards; Right pane docks the permanent Trade Ticket.
   - Position table highlights unrealized P&L, day's change, and one-click "Square Off" / "Trade".
6. **Preserve Reliability & Responsiveness**:
   - Retain full compatibility with existing Next.js 16 / React 19 pages, Tailwind configuration, and mock/live WebSocket & quote polling flows.
   - Seamlessly responsive on desktop, laptop, and tablet screens.

### Non-Goals
- Altering backend API contracts, Python services, or database models.
- Swapping the charting engine (`lightweight-charts`) — keep existing candle/RSI implementation while polishing its framing and timeframe buttons.
- Changing authentication mechanics or Kotak Neo session handshake logic.

### Anti-Goals
- Do not bloat the UI with excessive whitespace that forces active traders to scroll excessively.
- Do not introduce heavy runtime UI dependencies that slow down hot reload or bundle size.
- Do not break existing node test suites (`npm test` in `frontend/`).

---

## 3. Approaches Considered

1. **Approach 1: Direct Next.js Implementation (Selected)**
   - Re-architect `Layout.tsx`, global styling (`globals.css`, `market.css`), top index bar, watchlist tables, and the trading workspace directly in React/Tailwind.
   - *Pros*: Immediate working terminal in the browser with real quotes; zero transition delay.
   - *Cons*: Skips standalone Figma prototype iteration.
   - *Decision*: **Selected by user** for rapid tangible execution.

2. **Approach 2: Figma Design First, Then Code**
   - Build complete design system and mockups in Figma using Figma MCP tools, review, and then code.
   - *Pros*: Precise visual review before coding.
   - *Cons*: Adds an intermediate design cycle before functional code is written.

3. **Approach 3: Incremental In-Place Overhaul**
   - Update individual pages independently over multiple releases.
   - *Pros*: Low blast radius per step.
   - *Cons*: Creates an inconsistent, jarring visual experience between redesigned and legacy pages.

---

## 4. Architectural & UI Specifications

### 4.1 Design Tokens (CSS Variables & Tailwind)

```css
:root {
  /* Light Theme (Kotak Neo Light) */
  --bg: #F4F7FB;
  --panel: #FFFFFF;
  --panel-hover: #EDF2F9;
  --line: #D8E1EE;
  --text: #0F172A;
  --muted: #627289;
  --green: #059669;
  --red: #E11D48;
  --accent: #2563EB;
  --accent-dim: #DBEAFE;
}

.dark {
  /* Dark Theme (Kotak Neo Dark Navy) */
  --bg: #070B12;
  --panel: #0E1624;
  --panel-hover: #152033;
  --line: #1D2C42;
  --text: #F1F5F9;
  --muted: #7E90A8;
  --green: #00D09C;
  --red: #FF4757;
  --gold: #F59E0B;
  --accent: #2563EB;
  --accent-dim: #1E3A8A44;
}
```

### 4.2 Topbar & Persistent Index Ticker

- **Location:** Spans the top of `Layout.tsx` directly above page content.
- **Components:**
  - `IndexTickerStrip`: Polls or streams spot quotes for `NSE:NIFTY 50`, `BSE:SENSEX`, `NSE:NIFTY BANK`, `NSE:NIFTY FIN SERVICE`.
  - Automatically queries `/api/indices` on mount to obtain valid `spot.id`s and binds to `/api/market/quotes`.
  - Each chip displays:
    - Index name (`NIFTY 50`, `BANK NIFTY`)
    - Last Traded Price (LTP) with tabular formatting
    - Net change and percentage (`+124.50 (+0.52%)`)
    - Dynamic flash border/text on price update (`live-tick`)
  - Status indicators: Kotak Connected (Green pulse) / Paper (Amber), Mode Pill (`Paper` vs `Kotak account`), Theme Toggle, Kill-switch button (`Stop orders`).

### 4.3 Sidebar & Workspace Navigation

- Width: 230px, styled with dark navy glass finish (`background: var(--panel); border-right: 1px solid var(--line)`).
- Brand header with stylized Kotak Neo-inspired red-and-blue badge.
- Navigation links with active indicator bars, soft hover fills, and icon consistency (`lucide-react`).
- Bottom user profile pill with initials avatar, account type tag (`Kotak Live` vs `Simulated`), and logout trigger.

### 4.4 Watchlist & Slide-Over Quick Order Drawer (`MarketTable.tsx`, `OrderDrawer.tsx`, `Layout.tsx`)

- Compact rows with 36px–40px height for optimal trader scanning.
- Dynamic Action Overlay on hover:
  - Quick **B** button (`background: #2563EB; color: white; border-radius: 4px`) opens the Slide-Over Order Drawer pre-filled with `BUY`.
  - Quick **S** button (`background: #FF4757; color: white; border-radius: 4px`) opens the Slide-Over Order Drawer pre-filled with `SELL`.
  - Quick Chart trigger links directly to `/charts/?instrument=...`.
- Slide-Over Order Drawer:
  - Global drawer mounted in `Layout.tsx`, sliding in from the right edge with a backdrop click-to-dismiss and `Esc` key handler.
  - Allows full execution without navigating away from the current market overview or stock search.
- Price & % Change pill formatted with distinct background tint (e.g. `bg-emerald-500/10 text-emerald-400`).
- Multi-Watchlist Tabs:
  - Tab 1 ("My Watchlist") binds directly to the backend `/api/watchlist`.
  - Tabs 2–5 persist client-side in `localStorage`.
  - "Indices" and "F&O" tabs provide quick system feeds from `/api/indices` and `/api/contracts`.

### 4.5 Trading Workstation & Trade Ticket (`trading.tsx`, `TradeTicket.tsx`)

- **Positions & Orders**:
  - Live P&L Header card: Total P&L, Realized P&L, Margin Available, Collateral Used.
  - One-click "Square Off" button: Populates the docked Trade Ticket with the inverse position side and net quantity, focusing the ticket for swift user confirmation (prevents accidental unconfirmed live broker executions).
- **Trade Ticket**:
  - Active execution types: Fully functional `MARKET` and `LIMIT` orders mapped to backend schema.
  - Product type tabs: `Intraday (MIS)` / `Delivery (CNC)` / `Normal (NRML)` displayed with active state (mapped cleanly to equity/derivative order defaults).
  - Quantity input with quick stepper buttons (+1 lot, +5 lots, max lot limit).
  - Order estimation displays gross order value (`price * quantity`) and paper futures margin (20%).
  - High-visibility execution button: Neon blue for Buy, Vibrant red for Sell with loading spinner.

---

## 5. Architectural Calls Made

1. **Quick Order Drawer**: Global slide-over drawer mounted at the `Layout` level so clicking B/S anywhere in the app (Overview, Stocks, Indices) opens an instant order ticket over the page without navigating away.
2. **Order Types & Backend Compatibility**: Supported order types remain `MARKET` and `LIMIT` to avoid breaking backend schemas or raising HTTP 422 errors. `SL` and `SL-M` are slated for subsequent backend phases.
3. **Square-Off Safety**: "Square Off" does not execute immediately with a blind API call; it loads the reverse order into the Trade Ticket with one-click confirmation to protect real broker accounts.
4. **Multi-Watchlist Architecture**: Primary watchlist remains synchronized with Kotak Neo / database storage, with secondary custom tabs stored in `localStorage`.
5. **Index Quote Stream**: Spot IDs are fetched from `/api/indices` on mount and cached so the ticker smoothly animates on every 5s quote update.
