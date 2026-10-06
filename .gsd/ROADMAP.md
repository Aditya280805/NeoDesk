# ROADMAP.md

> **Current Phase**: 1
> **Milestone**: v2.0 (Instrument Details, Charting, and Theming)

## Must-Haves
- [ ] Backend API for historical chart data (1D, 5D, 1M, 1Y).
- [ ] Dynamic frontend route for Instrument Details (`/instrument/[symbol]`).
- [ ] Interactive charting integration.
- [ ] Light/Dark mode proper implementation.

## Phases

### Phase 1: Instrument Details Backend & History API
**Status**: ✅ Complete
- Create new FastAPI endpoints in `/api/market/history` for fetching candle data.
- Verify Kotak Neo history data capabilities and implement caching.

### Phase 2: Instrument Details Frontend Page
**Status**: ✅ Complete
- Create Next.js dynamic route `/instrument/[symbol]`.
- Build the layout for Fundamentals, Technicals, and Chart placeholder.
- Integrate interactive charting library (e.g., `lightweight-charts`).

### Phase 3: Global Theme Refactor (Light/Dark Mode)
- Refactor `globals.css` into proper CSS variables for Light and Dark themes.
- Implement theme toggle provider in Next.js.
