---
phase: 2
plan: 2
wave: 1
---

# Plan 2.1: Instrument Details Frontend Page

## Objective
Create a dynamic Next.js page for individual instruments (`/instrument/[id]`). It should serve as a comprehensive dashboard that integrates historical charting, live price data, and technical/fundamental information into a premium, responsive UI.

## Context
- `frontend/src/pages/instrument/[id].tsx` (Target)
- `frontend/src/components/PriceChart.tsx`
- `frontend/src/pages/charts.tsx` (Reference for chart loading)
- `frontend/src/styles/globals.css` (Target for layout styles)
- API Endpoints: `/api/instruments/{id}`, `/api/market/quotes`, `/api/market/history`

## Tasks

<task type="auto">
  <name>Create dynamic route and base dashboard layout</name>
  <files>
    - frontend/src/pages/instrument/[id].tsx
    - frontend/src/styles/globals.css
  </files>
  <action>
    - Create `[id].tsx` in `frontend/src/pages/instrument`.
    - Retrieve `id` from `useRouter()`.
    - Fetch static metadata using `api('/instruments/{id}')` and live data using `api('/market/quotes')` (similar to index.tsx).
    - Design a premium "blueish-black" dashboard layout (CSS grid) with the following regions:
      1. **Header**: Symbol name prominently displayed, current LTP, and percentage change.
      2. **Chart Area**: Spanning the central space.
      3. **Range Selector**: A button group for toggling [1D, 5D, 30D, 1Y, 5Y].
      4. **Data Panel**: A sidebar or bottom section displaying technical indicators (SMA, RSI) and basic instrument metadata (lot size, strike, tick size).
    - Add classes in `globals.css` to ensure the layout matches the modern, polished aesthetic requested by the user.
  </action>
  <verify>curl -s -o /dev/null -w "%{http_code}" http://localhost:3000/instrument/nse_cm%7C2885</verify>
  <done>Created `[id].tsx` with standard layout scaffolding and required API hooks fetching instrument context.</done>
</task>

<task type="auto">
  <name>Integrate dynamic PriceChart and Range Selector</name>
  <files>
    - frontend/src/pages/instrument/[id].tsx
  </files>
  <action>
    - Map the range selector buttons to the corresponding intervals and days: 
      - `1D` -> interval `1min`, days `1`
      - `5D` -> interval `5min`, days `5`
      - `30D` -> interval `60min`, days `30`
      - `1Y` -> interval `D`, days `365`
      - `5Y` -> interval `D`, days `1825` (fallback depending on backend constraints)
    - Fetch `/api/market/history` dynamically based on the active range state.
    - Wrap the `PriceChart` component (using dynamic import to avoid SSR issues) inside the Chart Area, passing the dynamically fetched history and current `id`.
  </action>
  <verify>grep -q "PriceChart" frontend/src/pages/instrument/\[id\].tsx</verify>
  <done>Chart reacts cleanly to range toggles and displays history data properly.</done>
</task>

<task type="auto">
  <name>Populate Technical and Meta Info Panel</name>
  <files>
    - frontend/src/pages/instrument/[id].tsx
  </files>
  <action>
    - Display current live technicals (derived from the latest elements of the history indicators array: SMA 20, 50, 200, and RSI 14).
    - Render "N/A" for unavailable core fundamentals (e.g. PE, Market Cap) explicitly to show intent, while filling available meta data like tick size, lot size, exchange, and instrument type from the `/api/instruments/{id}` response.
  </action>
  <verify>grep -q "SMA" frontend/src/pages/instrument/\[id\].tsx</verify>
  <done>The panel cleanly displays metrics directly derived from history indicators and instrument details.</done>
</task>

## Success Criteria
- [ ] Navigating to `/instrument/nse_cm|2885` loads a dedicated dashboard page.
- [ ] Selecting different time ranges correctly fetches new candle intervals and updates the chart.
- [ ] Technical indicators (SMA/RSI) and instrument specifics (lot size, type) are displayed neatly in the data panel.
- [ ] The dashboard adopts the "blueish-black" aesthetic.
