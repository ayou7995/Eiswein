---
name: Phase 0 patterns
description: Load-bearing frontend patterns established in Phase 0 — reuse in later phases before inventing new shapes.
type: project
---

Phase 0 scaffold established these reusable shapes. Later phases should extend these rather than parallel implementations.

**Why:** Duplication would violate the DRY rule (rule 7) and the strict modular boundaries rule (rule 3). The shapes were also reviewed against STAFF_REVIEW_DECISIONS.md so they already encode the locked contracts (B1, B2, B6, F2, F5, I17, I20).

**How to apply:**
- API boundary: add new endpoints as functions in `src/api/*.ts`, each with a Zod schema co-located. Call via `apiRequest(path, { schema })`. Never call `fetch` directly from pages/hooks.
- Error handling: switch on `EisweinApiError.code` (stable identifier per B6), never on `.message`. Structured payload lives in `.details`.
- Auth state: read `useAuth()` inside components. Never reach into cookies or localStorage (no tokens stored client-side at all).
- Refresh dedupe: the single-flight promise lives inside `src/api/client.ts`. Don't re-implement it per endpoint.
- Forms: `react-hook-form` + Zod resolver per F2. Define the form schema at the top of the page file.
- Route protection: wrap page trees in `<ProtectedRoute>`. Don't re-check auth inside individual pages.
- Signal badges: `SignalBadge` is the only surface for 🟢🟡🔴 indicators (I20 text+shape redundancy). When Phase 4 adds ActionBadge, compose on top of it rather than re-implementing the tone mapping.
- Tests: import `renderWithProviders` from `src/test/utils.tsx` when a component needs router + query + auth context.
