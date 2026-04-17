---
name: False Positives — Eiswein Security Patterns
description: Patterns that look dangerous but are confirmed acceptable in Eiswein's security model
type: project
---

# Confirmed False Positives

## test fixtures with bcrypt stub hashes
Strings like `$2b$12$x` and `$2b$12$h` in test files are seed values for repository unit tests — they are inserted directly into the DB column, never verified against real passwords in those tests. Not a hardcoded credential.

## eslint-disable for console.error in ErrorBoundary
`ErrorBoundary.tsx` has a single `// eslint-disable-next-line no-console` for `console.error` on genuine render errors. The comment explains why (render error = must log, sanitization is backend concern). Accepted.

## `test_password = "correcthorsebatterystaple-testing"` in conftest.py
This is a test fixture password, not a production credential. Acceptable.

## `jwt_secret="test" * 20` in conftest.py with `# noqa: S106`
Test fixture with noqa annotation. Acceptable — the S106 rule is explicitly suppressed with justification.

## CF IP ranges hardcoded in cf_ip_validation.py
The canonical Cloudflare IP ranges are embedded in code with a dated comment. This is intentional per E3 spec — `Settings.trusted_proxies` can extend the list. Not a security issue.

## `cookie_secure=False` in test settings
Test infrastructure only, never reaches production. Acceptable.
