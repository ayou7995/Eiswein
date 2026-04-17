---
name: Phase 0 Audit Findings
description: Critical security and contract issues found during Phase 0 static review (2026-04-17)
type: project
---

# Phase 0 Audit Findings (2026-04-17)

## CRITICAL: Frontend/Backend Login Contract Mismatch (3 issues)
1. Frontend sends `{password}` only; backend `LoginRequest` requires `{username, password}` — login returns 422 in production.
2. Backend `LoginResponse` is `{status: "ok", username: str}`; frontend Zod schema expects `{ok: true, user: {username, is_admin}}` — login response validation always fails.
3. Frontend calls `GET /api/v1/me` (in `useAuth` mount probe and `getCurrentUser()`); no `/me` endpoint exists in Phase 0 backend — auth context stuck on `loading`.

**Why:** Agent worktrees developed independently without cross-checking the API contract.
**How to apply:** Always verify frontend Zod schemas against backend Pydantic response_model before merging. The `/me` endpoint must be added to auth_routes.py.

## HIGH: slowapi installed but never wired
- `rate_limit.py` defines `build_limiter()` and `client_ip_key()` but neither is attached to `app.state.limiter`, no `SlowAPIMiddleware` added, no `@limiter.limit()` decorators on routes.
- Login endpoint has **no HTTP-layer rate limiting** despite config values existing.

## HIGH: openapi_url always exposed in production
- `docs_url` correctly gated on `environment != "production"`, but `openapi_url="/api/v1/openapi.json"` is hardcoded unconditionally.
- In production, the full OpenAPI JSON (all routes, schemas, auth flows) is publicly accessible.

## Acceptable (not false positive, but Phase 0 scope)
- No `/me` endpoint: acceptable for Phase 0 as a TODO, but auth context will be broken.
- Single eslint-disable in ErrorBoundary.tsx for console.error: justified.
- Test fixtures use hardcoded bcrypt hash stubs (`$2b$12$x`) — these are stub values only used as DB seeds in unit tests, not real password validation.
