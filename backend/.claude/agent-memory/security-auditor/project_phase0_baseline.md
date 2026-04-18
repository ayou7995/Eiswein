---
name: Eiswein Phase 0 Baseline
description: Security patterns established and verified in Phase 0 — skip re-flagging these
type: project
---

Phase 0 passed audit. The following patterns are intentional and correct:

- `assert isinstance(exc, EisweinError)` in error_handlers.py — FastAPI registers these handlers with type-narrowing asserts; they are not reachable via `python -O` in prod because uvicorn does not strip assertions, and the assertions guard programmer error not user input.
- `current_user_id` dependency reads `eiswein_access` httpOnly cookie (not localStorage). This is intentional and correct.
- `SecretStr` wrappers on jwt_secret, encryption_key, admin_password_hash, fred_api_key in config.py — secrets never exposed via `.model_dump()` or repr.
- structlog redactor in log pipeline catches `password|token|secret|key` key names recursively.
- No raw SQL strings anywhere — SQLAlchemy ORM or `sqlite_insert().on_conflict_do_update()` only.

**Why:** These were reviewed in Phase 0 and locked as correct patterns.
**How to apply:** Do not re-flag these as findings in future audits.
