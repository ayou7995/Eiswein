"""IP-based login throttling.

Design (per E5 in docs/STAFF_REVIEW_DECISIONS.md)
* 5 consecutive failed logins from same IP → lock the IP for 15 minutes.
* 20 failures/minute globally → emit audit + trigger email alert
  (the alert is fired from the caller, not this module, so we stay
   side-effect-free and testable).
* Never lock the account itself — that would let an attacker DoS
  the legitimate single user.

State is persisted in `audit_log` via a repository-like helper passed
in. This module is pure domain logic: it takes "recent attempts" and
returns decisions. The FastAPI layer stitches in the DB.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable


@dataclass(frozen=True, slots=True)
class AttemptRecord:
    """Single login attempt used for lockout calculation."""

    ip: str
    success: bool
    timestamp: datetime


@dataclass(frozen=True, slots=True)
class LockoutStatus:
    locked: bool
    attempts_remaining: int
    retry_after_seconds: int


def evaluate_ip_lockout(
    ip: str,
    recent_attempts: Iterable[AttemptRecord],
    *,
    threshold: int,
    window: timedelta,
    now: datetime | None = None,
) -> LockoutStatus:
    """Determine whether `ip` is locked out right now.

    A lockout triggers when we can find `threshold` consecutive failures
    from `ip` within `window`. While the lockout window is still active
    (last fail + window > now), we stay locked.
    """
    current = now or datetime.now(timezone.utc)
    ip_attempts = sorted(
        (a for a in recent_attempts if a.ip == ip),
        key=lambda a: a.timestamp,
        reverse=True,
    )

    consecutive_fails: list[AttemptRecord] = []
    for attempt in ip_attempts:
        if attempt.success:
            break
        consecutive_fails.append(attempt)

    fails_in_window = [a for a in consecutive_fails if current - a.timestamp <= window]

    if len(fails_in_window) >= threshold:
        last_fail = fails_in_window[0].timestamp
        unlock_at = last_fail + window
        retry_after = max(0, int((unlock_at - current).total_seconds()))
        return LockoutStatus(locked=True, attempts_remaining=0, retry_after_seconds=retry_after)

    remaining = max(0, threshold - len(fails_in_window))
    return LockoutStatus(locked=False, attempts_remaining=remaining, retry_after_seconds=0)


def global_failure_count(
    recent_attempts: Iterable[AttemptRecord],
    *,
    window: timedelta,
    now: datetime | None = None,
) -> int:
    current = now or datetime.now(timezone.utc)
    return sum(
        1 for a in recent_attempts if not a.success and current - a.timestamp <= window
    )
