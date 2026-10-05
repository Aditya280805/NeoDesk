---
phase: 4
plan: 2
wave: 1
---

# Plan 4.2: Order Ticket & Global Aesthetics Polish

## Objective
Smooth out interactive components, specifically the Order Ticket (`TradeTicket.tsx`). Ensure buttons provide clear loading state feedback and apply global styling polish to match a premium trading terminal feel.

## Context
- .gsd/SPEC.md
- frontend/src/components/TradeTicket.tsx
- frontend/src/styles/globals.css

## Tasks

<task type="auto">
  <name>Order Ticket Polish</name>
  <files>
    - frontend/src/components/TradeTicket.tsx
    - frontend/src/styles/globals.css
  </files>
  <action>
    - Update `TradeTicket.tsx` to add visual feedback (e.g., loading spinners or disabled states) while order placement requests are in flight.
    - Improve error handling UI within the ticket to show clean error banners rather than plain text.
    - Polish the buy/sell toggle buttons to look like native segmented controls.
    - Adjust `globals.css` with minor layout tweaks for better input padding, spacing, and modern terminal aesthetics (glassmorphism or tighter borders).
  </action>
  <verify>npm run lint</verify>
  <done>Trade ticket supports loading states, clear error messages, and features polished interactive controls.</done>
</task>

## Success Criteria
- [ ] Order submission buttons disable and indicate loading state during API calls.
- [ ] Errors are displayed cleanly inside the ticket.
- [ ] Global aesthetics (inputs, buttons) are refined and responsive.
