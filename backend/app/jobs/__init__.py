"""Scheduler-driven jobs package (Phase 6).

Each job module exposes a single top-level async function. The
scheduler wires them up in :mod:`app.jobs.scheduler`. Jobs:

* :mod:`app.jobs.daily_update` — wrap ``run_daily_update`` + optional
  summary email dispatch.
* :mod:`app.jobs.backup` — atomic SQLite backup using the
  ``Connection.backup()`` API, rotation to 30 days.
* :mod:`app.jobs.token_reminder` — nudge the user before Schwab refresh
  tokens expire.
* :mod:`app.jobs.vacuum` — monthly full ``VACUUM``, guarded by a
  "25-day-since-last-run" check so it never runs twice in quick
  succession.
* :mod:`app.jobs.email_dispatcher` — single-source email send path,
  no-op when SMTP is not configured.

Conventions shared by every job:

* Dependencies are injected via function parameters (rule 13).
* Exceptions are caught + logged inside each job (rule 14: scheduler
  never aborts because of one bad job).
* All timestamps persisted to ``system_metadata`` are UTC.
"""
