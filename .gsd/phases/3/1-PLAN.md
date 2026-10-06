---
phase: 3
plan: 1
wave: 1
---

# Plan 3.1: Global Theme Refactor (Light/Dark Mode)

## Objective
Implement proper light and dark themes using standard CSS variables and `next-themes` to allow toggling a smooth light mode alongside the existing dark mode.

## Context
- `frontend/src/styles/globals.css` (Target for refactor)
- `frontend/src/pages/_app.tsx` (Target for ThemeProvider)
- `frontend/src/components/Layout.tsx` (Target for adding a toggle button)
- User explicitly requested: "Change the theme, make it to a blueish and blackish" and a "clean, smooth interface for both light and dark modes."

## Tasks

<task type="auto">
  <name>Install next-themes and define CSS variables</name>
  <files>
    - frontend/package.json
    - frontend/src/styles/globals.css
  </files>
  <action>
    - Change directory to `frontend` and run `npm install next-themes`.
    - Modify `:root` in `globals.css` to define the default Light theme variables (e.g. `--bg: #f8fafc; --panel: #ffffff; --text: #0f172a; --line: #e2e8f0;`).
    - Add `.dark` class to `globals.css` redefining these variables for the Dark theme (blueish-black, `#050505` backgrounds).
    - Refactor all hardcoded hex color values across classes in `globals.css` to use CSS variables so they respond to the theme toggle.
  </action>
  <verify>grep -q "next-themes" frontend/package.json</verify>
  <done>next-themes is installed and globals.css has full variable coverage for colors.</done>
</task>

<task type="auto">
  <name>Implement ThemeProvider and Toggle Button</name>
  <files>
    - frontend/src/pages/_app.tsx
    - frontend/src/components/Layout.tsx
  </files>
  <action>
    - Wrap the `Component` in `_app.tsx` inside `<ThemeProvider attribute="class" defaultTheme="dark">`.
    - In `Layout.tsx`, import `useTheme` from `next-themes` and `Sun`, `Moon` icons from `lucide-react`.
    - Add a toggle button in the `topbar` section that switches between light and dark modes when clicked. Ensure we handle hydration mismatch by returning early if not mounted.
  </action>
  <verify>grep -q "ThemeProvider" frontend/src/pages/_app.tsx</verify>
  <done>The application renders wrapped in a ThemeProvider and a functional toggle button is visible in the top bar.</done>
</task>

## Success Criteria
- [ ] Clicking the theme toggle switches between Light and Dark mode.
- [ ] CSS uses class-based `.dark` switching.
- [ ] The aesthetic is clean and modern in both light and dark variants.
