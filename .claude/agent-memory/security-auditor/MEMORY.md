# Security Auditor Memory Index

## Project Patterns
- [Phase 0 Audit Findings](phase0_audit_findings.md) — Critical frontend/backend contract mismatches found in Phase 0; slowapi installed but never wired; openapi_url always exposed
- [Phase 5 Audit Findings](phase5_audit_findings.md) — Phase 5 clean (no CRITICAL/HIGH); one MEDIUM: GET /positions missing rate limit; all IDOR/PnL/auth/lock checks passed
- [Phase 6 Audit Findings](phase6_audit_findings.md) — Phase 6: 0 CRITICAL, 1 HIGH (backup file permissions chmod 600 missing), 2 MEDIUM (SMTP exc log, python-jose CVEs)
- [False Positives](false_positives.md) — Patterns that look dangerous but are acceptable in Eiswein context
