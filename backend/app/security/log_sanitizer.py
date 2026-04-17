"""Structlog processor + helper for scrubbing secrets from log payloads.

Per E6: any dict key matching `/password|token|secret|key/i` is replaced
with `[REDACTED]` recursively. Applies before the formatter so neither
stdout nor downstream sinks see the real value.
"""

from __future__ import annotations

import re
from collections.abc import MutableMapping
from typing import Any

REDACTED = "[REDACTED]"
_SENSITIVE_KEY = re.compile(r"password|token|secret|key", re.IGNORECASE)


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: (REDACTED if _SENSITIVE_KEY.search(k) else _redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v) for v in value]
    if isinstance(value, tuple):
        return tuple(_redact(v) for v in value)
    return value


def sanitize_log_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a deep copy with sensitive keys redacted."""
    result = _redact(payload)
    assert isinstance(result, dict)
    return result


def structlog_redactor(
    _logger: Any,
    _method_name: str,
    event_dict: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    """Structlog processor: redact sensitive keys in-place on the event dict."""
    for k in list(event_dict.keys()):
        if _SENSITIVE_KEY.search(k):
            event_dict[k] = REDACTED
        else:
            event_dict[k] = _redact(event_dict[k])
    return event_dict
