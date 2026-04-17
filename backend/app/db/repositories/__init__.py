"""Repository layer — the only place in the codebase that writes SQL.

Rule 3 (Clean Architecture) + I9 (audit log is append-only) are enforced
here. API routes depend on repositories via FastAPI DI; indicators never
touch the DB directly (Hard Operational Invariant).
"""
