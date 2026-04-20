"""Outbound email for scheduler jobs (Phase 6).

Two public entry points:

* :func:`send_daily_summary` — HTML + plain-text digest derived from
  :class:`app.ingestion.daily_ingestion.DailyUpdateResult` plus the
  per-ticker :class:`TickerSnapshot` rows for the session day.
* :func:`send_token_expiry_alert` — short alert for an upcoming Schwab
  refresh token expiry.

Design
------
* ``SMTP_HOST`` unset ⇒ no-op with a structured log. Local dev + CI
  work without a mail relay, and a misconfigured deploy surfaces as a
  loud "email_skipped: not_configured" line rather than silent
  drops (rule 14 — graceful degradation; rule 15 — observable).
* Jinja2 renders with ``autoescape=True`` so user-controlled strings
  (ticker symbols, broker name) cannot inject HTML. Plain-text bodies
  are assembled from the same data object rather than by HTML-
  stripping — keeps the text body semantically meaningful.
* ``smtplib`` (stdlib) is used synchronously. The job runs out-of-band
  of request handling, so blocking for a couple seconds on SMTP is
  fine, and avoiding ``aiosmtplib`` keeps the dependency footprint
  smaller.
* No passwords, tokens, or other credentials appear in any rendered
  body or log field (rule 15 + CLAUDE.md log sanitizer rule).
"""

from __future__ import annotations

import smtplib
import ssl
from datetime import datetime
from decimal import Decimal
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Protocol

import structlog
from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.config import Settings
from app.ingestion.daily_ingestion import DailyUpdateResult
from app.signals.types import ActionCategory, MarketPosture, TimingModifier

logger = structlog.get_logger("eiswein.jobs.email")


_TEMPLATES_DIR = Path(__file__).parent / "templates"
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(enabled_extensions=("html",), default=True),
    keep_trailing_newline=False,
)


class TickerSummaryRow(Protocol):
    """Structural type for the snapshot rows the daily-summary email needs.

    Accepts either :class:`app.db.models.TickerSnapshot` or any mock /
    fake with the same shape — which keeps the email dispatcher free
    of a direct SQLAlchemy dependency beyond the read-only attribute
    surface.
    """

    symbol: str
    action: str
    timing_modifier: str
    show_timing_modifier: bool
    entry_ideal: Decimal | None
    stop_loss: Decimal | None


# Actions that demand attention — anything that isn't steady-state
# "hold" or "watch". These are the only rows the daily email surfaces.
_ATTENTION_ACTIONS: frozenset[str] = frozenset(
    {
        ActionCategory.STRONG_BUY.value,
        ActionCategory.BUY.value,
        ActionCategory.REDUCE.value,
        ActionCategory.EXIT.value,
    }
)


_ACTION_LABELS: dict[str, str] = {
    ActionCategory.STRONG_BUY.value: "強力買入 🟢🟢",
    ActionCategory.BUY.value: "買入 🟢",
    ActionCategory.HOLD.value: "持有 ✓",
    ActionCategory.WATCH.value: "觀望 👀",
    ActionCategory.REDUCE.value: "減倉 ⚠️",
    ActionCategory.EXIT.value: "出場 🔴🔴",
}

_ACTION_COLORS: dict[str, str] = {
    ActionCategory.STRONG_BUY.value: "#047857",
    ActionCategory.BUY.value: "#059669",
    ActionCategory.HOLD.value: "#374151",
    ActionCategory.WATCH.value: "#6b7280",
    ActionCategory.REDUCE.value: "#b45309",
    ActionCategory.EXIT.value: "#b91c1c",
}

_TIMING_LABELS: dict[str, str] = {
    TimingModifier.FAVORABLE.value: "✓ 時機好",
    TimingModifier.MIXED.value: "持平",
    TimingModifier.UNFAVORABLE.value: "⏳ 等回調",
}

_POSTURE_LABELS: dict[str, str] = {
    MarketPosture.OFFENSIVE.value: "進攻 🟢",
    MarketPosture.NORMAL.value: "正常",
    MarketPosture.DEFENSIVE.value: "防守 🔴",
}

_POSTURE_COLORS: dict[str, tuple[str, str]] = {
    MarketPosture.OFFENSIVE.value: ("#ecfdf5", "#047857"),
    MarketPosture.NORMAL.value: ("#f3f4f6", "#4b5563"),
    MarketPosture.DEFENSIVE.value: ("#fef2f2", "#b91c1c"),
}


def _not_configured(settings: Settings) -> bool:
    """SMTP host is the minimum required config — treat anything else
    as 'plausible partial config' we still log through.
    """
    return not settings.smtp_host


def send_daily_summary(
    *,
    result: DailyUpdateResult,
    snapshots: list[TickerSummaryRow],
    settings: Settings,
) -> bool:
    """Render + send the daily summary email.

    Returns ``True`` when a send was attempted and succeeded,
    ``False`` when SMTP is not configured or delivery failed. Never
    raises — email is a side-channel, the scheduler must not abort
    on a flaky relay.
    """
    if _not_configured(settings):
        logger.info("email_skipped", reason="not_configured", job="daily_summary")
        return False

    recipient = settings.smtp_to
    sender = settings.smtp_from
    if not recipient or not sender:
        logger.info(
            "email_skipped",
            reason="missing_from_or_to",
            job="daily_summary",
        )
        return False

    ctx = _build_daily_context(result=result, snapshots=snapshots)
    html_body = _env.get_template("daily_summary.html").render(**ctx)
    text_body = _render_daily_text(ctx)
    subject = f"Eiswein 每日摘要 — {result.session_date} ({ctx['posture_label']})"

    return _dispatch(
        settings=settings,
        sender=sender,
        recipient=recipient,
        subject=subject,
        html_body=html_body,
        text_body=text_body,
        job_name="daily_summary",
    )


def send_token_expiry_alert(
    *,
    days_remaining: int,
    expires_at: datetime,
    broker: str,
    settings: Settings,
) -> bool:
    """Render + send the token-expiry alert.

    Same contract as :func:`send_daily_summary`: never raises, returns
    ``True`` on successful send.
    """
    if _not_configured(settings):
        logger.info("email_skipped", reason="not_configured", job="token_expiry")
        return False

    recipient = settings.smtp_to
    sender = settings.smtp_from
    if not recipient or not sender:
        logger.info(
            "email_skipped",
            reason="missing_from_or_to",
            job="token_expiry",
        )
        return False

    ctx: dict[str, Any] = {
        "days_remaining": max(days_remaining, 0),
        "expires_at": expires_at.strftime("%Y-%m-%d %H:%M UTC"),
        "broker": broker,
    }
    html_body = _env.get_template("token_alert.html").render(**ctx)
    text_body = (
        f"Eiswein: {broker} refresh token 將於 {ctx['days_remaining']} 天後到期"
        f"（{ctx['expires_at']}）。請登入 Eiswein → 設定 → 重新連接。"
    )
    subject = f"[Eiswein] Broker token expires in {ctx['days_remaining']} day(s)"
    return _dispatch(
        settings=settings,
        sender=sender,
        recipient=recipient,
        subject=subject,
        html_body=html_body,
        text_body=text_body,
        job_name="token_expiry",
    )


def _build_daily_context(
    *,
    result: DailyUpdateResult,
    snapshots: list[TickerSummaryRow],
) -> dict[str, Any]:
    posture_value = (
        result.market_posture.value
        if result.market_posture is not None
        else MarketPosture.NORMAL.value
    )
    posture_bg, posture_border = _POSTURE_COLORS.get(
        posture_value, _POSTURE_COLORS[MarketPosture.NORMAL.value]
    )
    posture_label = _POSTURE_LABELS.get(posture_value, posture_value)

    attention = []
    for snap in snapshots:
        if snap.action not in _ATTENTION_ACTIONS:
            continue
        attention.append(
            {
                "symbol": snap.symbol,
                "action_label": _ACTION_LABELS.get(snap.action, snap.action),
                "action_color": _ACTION_COLORS.get(snap.action, "#374151"),
                "timing_label": (
                    _TIMING_LABELS.get(snap.timing_modifier, "")
                    if snap.show_timing_modifier
                    else ""
                ),
            }
        )
    attention.sort(key=lambda r: (_attention_sort_key(r["action_label"]), r["symbol"]))

    return {
        "session_date": result.session_date.isoformat(),
        "posture_label": posture_label,
        "posture_bg": posture_bg,
        "posture_border": posture_border,
        "attention_items": attention,
        "symbols_requested": result.symbols_requested,
        "symbols_succeeded": result.symbols_succeeded,
        "symbols_failed": result.symbols_failed,
        "symbols_delisted": result.symbols_delisted,
        "indicators_ok": result.indicators_computed_symbols,
        "snapshots_ok": result.snapshots_composed,
        "macro_rows": result.macro_rows_upserted,
        "macro_failed": result.macro_series_failed,
    }


_ATTENTION_SORT_ORDER: dict[str, int] = {
    _ACTION_LABELS[ActionCategory.EXIT.value]: 0,
    _ACTION_LABELS[ActionCategory.REDUCE.value]: 1,
    _ACTION_LABELS[ActionCategory.STRONG_BUY.value]: 2,
    _ACTION_LABELS[ActionCategory.BUY.value]: 3,
}


def _attention_sort_key(label: str) -> int:
    return _ATTENTION_SORT_ORDER.get(label, 99)


def _render_daily_text(ctx: dict[str, Any]) -> str:
    lines = [
        f"Eiswein 每日摘要 — {ctx['session_date']}",
        f"大盤狀態: {ctx['posture_label']}",
        "",
        "需要注意:",
    ]
    if ctx["attention_items"]:
        for row in ctx["attention_items"]:
            timing = f" [{row['timing_label']}]" if row["timing_label"] else ""
            lines.append(f"  - {row['symbol']}: {row['action_label']}{timing}")
    else:
        lines.append("  (無)")
    lines.extend(
        [
            "",
            "執行摘要:",
            f"  - 成功 {ctx['symbols_succeeded']}/{ctx['symbols_requested']} 檔",
            f"  - 失敗 {ctx['symbols_failed']} 檔 / 下市 {ctx['symbols_delisted']} 檔",
            f"  - 指標 {ctx['indicators_ok']} 檔，快照 {ctx['snapshots_ok']} 檔",
            f"  - Macro 寫入 {ctx['macro_rows']} 筆 (失敗 {ctx['macro_failed']} series)",
            "",
            "Eiswein — 僅供決策參考，非自動下單系統。",
        ]
    )
    return "\n".join(lines)


def _dispatch(
    *,
    settings: Settings,
    sender: str,
    recipient: str,
    subject: str,
    html_body: str,
    text_body: str,
    job_name: str,
) -> bool:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = recipient
    message.set_content(text_body, charset="utf-8")
    message.add_alternative(html_body, subtype="html")

    host = settings.smtp_host
    if host is None:
        # Defensive: _not_configured already checked this — keep mypy
        # happy without a cast.
        logger.info("email_skipped", reason="not_configured", job=job_name)
        return False
    port = settings.smtp_port
    timeout = settings.smtp_timeout_seconds

    try:
        with smtplib.SMTP(host=host, port=port, timeout=timeout) as smtp:
            smtp.ehlo()
            if settings.smtp_starttls:
                smtp.starttls(context=ssl.create_default_context())
                smtp.ehlo()
            if settings.smtp_username and settings.smtp_password is not None:
                smtp.login(
                    settings.smtp_username,
                    settings.smtp_password.get_secret_value(),
                )
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        # SMTPAuthenticationError response strings can echo back the
        # username ("535 5.7.8 Error: authentication failed: user@host").
        # Redact the message in that branch so log aggregators don't
        # collect usernames (security audit MEDIUM: smtp-exception-log-string).
        safe_error = "[redacted]" if isinstance(exc, smtplib.SMTPAuthenticationError) else str(exc)
        logger.warning(
            "email_send_failed",
            job=job_name,
            error_type=type(exc).__name__,
            error=safe_error,
        )
        return False

    logger.info("email_sent", job=job_name, subject=subject)
    return True
