---
name: Phase 5 Audit Findings
description: Security findings from Phase 5 review (positions CRUD, history, settings, password change); all critical checks passed; two medium issues found
type: project
---

# Phase 5 Audit Findings (2026-04-19)

## Result: CLEAN — No CRITICAL or HIGH findings

## MEDIUM findings

### 1. `list_positions` (GET) has no rate limit decorator
`positions_routes.py` — the GET /positions route is a sync def with no `@limiter.limit()`.
The mutating write routes (POST /positions, /add, /reduce) all have limiters. The read
endpoint is lower risk but still touches the DB on every call. Low-abuse risk given
Cloudflare Access is the outer layer, but inconsistent with the pattern on other GET routes.

### 2. `_db_size_bytes` exposes the database file path in `settings_routes.py`
The function parses `settings.database_url` with `engine_url[len(prefix):]` and calls
`Path(path_str).stat()`. The path is never surfaced to the client (only `db_size_bytes: int`
is returned), so there is no information leak. Confirmed false-positive-like — the path
stays server-side. Note for future: if error messages from `OSError` were ever forwarded,
the path would leak. Currently safe.

## Confirmed Clean (critical checklist)

1. IDOR: `get_by_id(user_id=, position_id=)`, `list_for_position(user_id=, ...)`,
   `list_for_user(user_id=)` all filter by user_id in repository AND route. Defense in depth confirmed.
2. realized_pnl: `AdjustPositionRequest` has no `realized_pnl` field. Computed
   server-side in `apply_sell()` from stored `avg_cost`. Client cannot inject it.
3. Password change: bcrypt.checkpw used, zxcvbn+length gate enforced, no password in
   any audit detail, 5/min rate limit applied, BCRYPT_ROUNDS=12.
4. Race conditions: `get_position_lock(position_id)` held across full read-modify-write
   in add/reduce/close. Lock key is correctly scoped by position_id (not symbol/user).
5. Partial unique index: migration 0005 uses `op.create_index(..., unique=True,
   sqlite_where=sa.text("closed_at IS NULL"))` — correctly prevents double-open.
6. CHECK constraints: shares >= 0 / avg_cost >= 0 on positions; shares > 0 /
   price > 0 / side IN ('buy','sell') on trades. Both in model AND migration.
7. Auth on all routes: all 6 position routes, 3 history routes, 4 settings routes
   all have `user_id: int = Depends(current_user_id)`.
8. data-refresh rate limit: `@limiter.limit("1/hour")` confirmed.
9. No raw SQL: all queries use SQLAlchemy ORM / select() constructs.
10. Audit log PII: `_sanitize_details()` redacts password/token/secret keys. Audit
    query strictly scoped to `user_id`. No cross-user leak.
11. system-info: exposes only aggregate counts + db_size_bytes. No file paths, no
    internal details in response.
12. Frontend: no dangerouslySetInnerHTML anywhere. AuditRow renders extracted primitive
    fields (symbol, outcome) as text — not raw JSON. No XSS vector.
13. Password form: autoComplete="current-password" / "new-password" set correctly.
    Error message for wrong password is hardcoded Chinese string, not backend verbatim.
14. Client never sends realized_pnl / user_id / created_at in any POST body.
15. Modal: proper focus trap, Escape-to-close, backdrop mousedown close, focus restore.
16. History/decisions: trades.list_for_user scoped by user_id; snapshot lookup by symbol
    only touches TickerSnapshot (market-wide, no user data). No cross-user leak.

## False positive to remember
- `_db_size_bytes` parsing the DB URL string: looks like path exposure but the path
  is never returned to the client. Acceptable.
- `summaryFields` in AuditRow: only pulls `outcome` and `symbol` string fields from
  details dict; renders as React text node (auto-escaped). Not an XSS vector.
