---
phase: 3
plan: 3
wave: 3
gap_closure: true
---

# Plan 3.3: Gap Closure - Fix Frontend Build

## Objective
Fix the frontend build failure caused by missing `api.ts` and `useQuotes.ts` in `src/lib`.

## Context
- The verification step found that the frontend build fails.
- Missing files: `frontend/src/lib/api.ts` and `frontend/src/lib/useQuotes.ts`.

## Tasks

<task type="auto">
  <name>Create missing lib files</name>
  <files>
    - frontend/src/lib/api.ts
    - frontend/src/lib/useQuotes.ts
  </files>
  <action>
    - Ensure `api.ts` exports necessary API client utilities or mocked versions.
    - Ensure `useQuotes.ts` exports a React hook for fetching/subscribing to market quotes.
    - Resolve all import errors in the frontend so the build passes.
  </action>
  <verify>npm run build --prefix frontend</verify>
  <done>Frontend builds successfully</done>
</task>

## Success Criteria
- [ ] `npm run build` succeeds in the `frontend` directory.
