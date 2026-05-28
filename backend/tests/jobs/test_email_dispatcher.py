"""Tests for the Phase 6 email dispatcher.

SMTP is never actually hit — :mod:`smtplib.SMTP` is patched so the
test assertion surface is the rendered message + dispatch decision,
not network behavior.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from pydantic import SecretStr

from app.config import Settings
from app.ingestion.daily_ingestion import DailyUpdateResult
from app.jobs import email_dispatcher
from app.signals.types import ActionCategory, MarketPosture, TimingModifier


@dataclass
class _Snap:
    symbol: str
    action: str
    timing_modifier: str = TimingModifier.MIXED.value
    show_timing_modifier: bool = False
    entry_ideal: Decimal | None = None
    stop_loss: Decimal | None = None


def _base_result(
    *,
    market_open: bool = True,
    posture: MarketPosture | None = MarketPosture.NORMAL,
) -> DailyUpdateResult:
    return DailyUpdateResult(
        market_open=market_open,
        session_date=date(2026, 4, 17),
        symbols_requested=5,
        symbols_succeeded=4,
        symbols_failed=1,
        symbols_delisted=0,
        price_rows_upserted=100,
        macro_rows_upserted=12,
        macro_series_failed=0,
        indicators_computed_symbols=4,
        indicators_failed_symbols=0,
        snapshots_composed=4,
        snapshots_failed=0,
        market_posture=posture,
    )


def _configured_settings(
    base: Settings,
    **overrides: object,
) -> Settings:
    data = base.model_dump()
    data.update(
        {
            "smtp_host": "smtp.example.test",
            "smtp_port": 587,
            "smtp_username": "eiswein",
            "smtp_password": SecretStr("password-secret"),
            "smtp_from": "eiswein@example.test",
            "smtp_to": "user@example.test",
            "smtp_starttls": True,
        }
    )
    data.update(overrides)
    # SecretStr fields need to survive model_dump → model re-init;
    # pydantic returns plain strings, so we re-wrap.
    for field in ("jwt_secret", "encryption_key", "admin_password_hash", "smtp_password"):
        value = data.get(field)
        if isinstance(value, str):
            data[field] = SecretStr(value)
    return Settings.model_validate(data)


# ---------- not_configured short-circuits --------------------------------


def test_daily_summary_not_configured_does_not_hit_smtplib(settings: Settings) -> None:
    result = _base_result()
    with patch.object(email_dispatcher, "smtplib") as smtp_mod:
        ok = email_dispatcher.send_daily_summary(
            result=result,
            snapshots=[],
            settings=settings,
        )
    assert ok is False
    smtp_mod.SMTP.assert_not_called()


def test_token_alert_not_configured_does_not_hit_smtplib(settings: Settings) -> None:
    with patch.object(email_dispatcher, "smtplib") as smtp_mod:
        ok = email_dispatcher.send_token_expiry_alert(
            days_remaining=1,
            expires_at=datetime(2026, 4, 20, tzinfo=UTC),
            broker="schwab",
            settings=settings,
        )
    assert ok is False
    smtp_mod.SMTP.assert_not_called()


# ---------- configured: calls smtplib with expected message --------------


def test_daily_summary_sends_expected_message(settings: Settings) -> None:
    cfg = _configured_settings(settings)
    result = _base_result(posture=MarketPosture.OFFENSIVE)
    snapshots = [
        _Snap(symbol="AAPL", action=ActionCategory.STRONG_BUY.value),
        _Snap(symbol="TSLA", action=ActionCategory.EXIT.value),
        _Snap(symbol="MSFT", action=ActionCategory.HOLD.value),  # suppressed
    ]

    smtp_instance = MagicMock()
    smtp_ctx = MagicMock()
    smtp_ctx.__enter__.return_value = smtp_instance
    smtp_ctx.__exit__.return_value = False

    with patch.object(email_dispatcher.smtplib, "SMTP", return_value=smtp_ctx) as smtp_ctor:
        ok = email_dispatcher.send_daily_summary(
            result=result,
            snapshots=snapshots,
            settings=cfg,
        )

    assert ok is True
    smtp_ctor.assert_called_once_with(
        host="smtp.example.test",
        port=587,
        timeout=cfg.smtp_timeout_seconds,
    )
    smtp_instance.starttls.assert_called_once()
    smtp_instance.login.assert_called_once_with("eiswein", "password-secret")

    sent_msg = smtp_instance.send_message.call_args.args[0]
    assert sent_msg["From"] == "eiswein@example.test"
    assert sent_msg["To"] == "user@example.test"
    assert "2026-04-17" in sent_msg["Subject"]

    payload = sent_msg.as_string()
    # HOLD row must NOT appear in the attention list.
    assert "MSFT" not in payload
    # STRONG_BUY and EXIT rows must appear.
    assert "AAPL" in payload
    assert "TSLA" in payload


def test_daily_summary_suppresses_smtp_failure(settings: Settings) -> None:
    import smtplib as real_smtplib

    cfg = _configured_settings(settings)
    result = _base_result()

    smtp_ctx = MagicMock()
    smtp_ctx.__enter__.side_effect = real_smtplib.SMTPConnectError(421, "down")
    smtp_ctx.__exit__.return_value = False

    with patch.object(email_dispatcher.smtplib, "SMTP", return_value=smtp_ctx):
        ok = email_dispatcher.send_daily_summary(
            result=result,
            snapshots=[],
            settings=cfg,
        )

    assert ok is False


def test_jinja_autoescape_prevents_html_injection(settings: Settings) -> None:
    cfg = _configured_settings(settings)
    result = _base_result(posture=MarketPosture.NORMAL)
    # Deliberately inject a <script> tag via the symbol field. Jinja
    # must HTML-escape it in the rendered body.
    malicious = _Snap(
        symbol="<script>alert('x')</script>",
        action=ActionCategory.EXIT.value,
    )

    smtp_instance = MagicMock()
    smtp_ctx = MagicMock()
    smtp_ctx.__enter__.return_value = smtp_instance
    smtp_ctx.__exit__.return_value = False

    with patch.object(email_dispatcher.smtplib, "SMTP", return_value=smtp_ctx):
        email_dispatcher.send_daily_summary(
            result=result,
            snapshots=[malicious],
            settings=cfg,
        )

    sent_msg = smtp_instance.send_message.call_args.args[0]
    # Walk alternatives — HTML part is the one we need to assert on.
    html_parts = [part for part in sent_msg.walk() if part.get_content_type() == "text/html"]
    assert html_parts, "HTML alternative missing"
    html_body = html_parts[0].get_payload(decode=True).decode("utf-8")
    assert "<script>alert" not in html_body  # escaped
    assert "&lt;script&gt;" in html_body


def test_token_alert_renders_and_sends(settings: Settings) -> None:
    cfg = _configured_settings(settings)
    smtp_instance = MagicMock()
    smtp_ctx = MagicMock()
    smtp_ctx.__enter__.return_value = smtp_instance
    smtp_ctx.__exit__.return_value = False

    with patch.object(email_dispatcher.smtplib, "SMTP", return_value=smtp_ctx):
        ok = email_dispatcher.send_token_expiry_alert(
            days_remaining=1,
            expires_at=datetime(2026, 4, 21, 9, 0, tzinfo=UTC),
            broker="schwab",
            settings=cfg,
        )

    assert ok is True
    sent_msg = smtp_instance.send_message.call_args.args[0]
    assert "Broker token expires in 1 day" in sent_msg["Subject"]
    assert "schwab" in sent_msg.as_string()


def test_password_never_leaks_into_rendered_body(settings: Settings) -> None:
    cfg = _configured_settings(settings)
    result = _base_result()

    smtp_instance = MagicMock()
    smtp_ctx = MagicMock()
    smtp_ctx.__enter__.return_value = smtp_instance
    smtp_ctx.__exit__.return_value = False

    with patch.object(email_dispatcher.smtplib, "SMTP", return_value=smtp_ctx):
        email_dispatcher.send_daily_summary(
            result=result,
            snapshots=[],
            settings=cfg,
        )

    sent_msg = smtp_instance.send_message.call_args.args[0]
    body = sent_msg.as_string()
    assert "password-secret" not in body


@pytest.mark.parametrize(
    "posture",
    [MarketPosture.OFFENSIVE, MarketPosture.NORMAL, MarketPosture.DEFENSIVE, None],
)
def test_context_covers_every_posture(settings: Settings, posture: MarketPosture | None) -> None:
    cfg = _configured_settings(settings)
    result = _base_result(posture=posture)

    smtp_instance = MagicMock()
    smtp_ctx = MagicMock()
    smtp_ctx.__enter__.return_value = smtp_instance
    smtp_ctx.__exit__.return_value = False

    with patch.object(email_dispatcher.smtplib, "SMTP", return_value=smtp_ctx):
        ok = email_dispatcher.send_daily_summary(
            result=result,
            snapshots=[],
            settings=cfg,
        )
    assert ok is True


# ---------- catalyst digest ----------------------------------------------


def _fake_event(
    *,
    event_date: date,
    type_: str,
    title: str,
    ticker: str | None = None,
    event_time: str | None = None,
) -> object:
    """Minimal duck-typed event stand-in so we don't depend on the DB
    model in unit tests."""

    @dataclass
    class _Evt:
        event_date: date
        type: str
        title: str
        ticker_symbol: str | None
        event_time: str | None

    return _Evt(
        event_date=event_date,
        type=type_,
        title=title,
        ticker_symbol=ticker,
        event_time=event_time,
    )


def test_catalyst_digest_skips_when_no_events(settings: Settings) -> None:
    cfg = _configured_settings(settings)
    with patch.object(email_dispatcher, "smtplib") as smtp_mod:
        ok = email_dispatcher.send_catalyst_digest(
            events=[],
            as_of=date(2026, 5, 27),
            settings=cfg,
        )
    assert ok is False
    smtp_mod.SMTP.assert_not_called()


def test_catalyst_digest_skips_when_not_configured(settings: Settings) -> None:
    events = [
        _fake_event(
            event_date=date(2026, 5, 27),
            type_="earnings",
            title="AAPL Earnings",
            ticker="AAPL",
        )
    ]
    with patch.object(email_dispatcher, "smtplib") as smtp_mod:
        ok = email_dispatcher.send_catalyst_digest(
            events=events,  # type: ignore[arg-type]
            as_of=date(2026, 5, 27),
            settings=settings,
        )
    assert ok is False
    smtp_mod.SMTP.assert_not_called()


def _extract_bodies(message: object) -> tuple[str, str]:
    """Return (text, html) bodies decoded as UTF-8.

    EmailMessage's ``as_string()`` runs quoted-printable encoding which
    mangles Chinese characters for substring assertions — pull the
    parts directly and decode.
    """
    text_body = ""
    html_body = ""
    for part in message.iter_parts():  # type: ignore[attr-defined]
        ctype = part.get_content_type()
        payload = part.get_content()
        if ctype == "text/plain":
            text_body = payload
        elif ctype == "text/html":
            html_body = payload
    return text_body, html_body


def test_catalyst_digest_sends_when_events_present(settings: Settings) -> None:
    cfg = _configured_settings(settings)
    events = [
        _fake_event(
            event_date=date(2026, 5, 27),
            type_="macro",
            title="CPI Release",
            event_time="8:30 ET",
        ),
        _fake_event(
            event_date=date(2026, 5, 28),
            type_="earnings",
            title="AAPL Earnings",
            ticker="AAPL",
            event_time="AMC",
        ),
    ]

    smtp_instance = MagicMock()
    smtp_ctx = MagicMock()
    smtp_ctx.__enter__.return_value = smtp_instance
    smtp_ctx.__exit__.return_value = False

    with patch.object(email_dispatcher.smtplib, "SMTP", return_value=smtp_ctx):
        ok = email_dispatcher.send_catalyst_digest(
            events=events,  # type: ignore[arg-type]
            as_of=date(2026, 5, 27),
            horizon_days=3,
            settings=cfg,
        )

    assert ok is True
    sent = smtp_instance.send_message.call_args.args[0]
    text_body, html_body = _extract_bodies(sent)
    # Both events surfaced in the rendered body.
    assert "CPI Release" in html_body
    assert "AAPL Earnings" in html_body
    assert "CPI Release" in text_body
    # Subject carries the event count + horizon.
    assert sent["Subject"].startswith("📅 Eiswein 催化劑摘要")
    assert "未來 3 天" in sent["Subject"]
    assert "2 件事件" in sent["Subject"]


def test_catalyst_digest_groups_events_by_date(settings: Settings) -> None:
    cfg = _configured_settings(settings)
    events = [
        _fake_event(
            event_date=date(2026, 5, 28),
            type_="earnings",
            title="MSFT Earnings",
            ticker="MSFT",
        ),
        _fake_event(
            event_date=date(2026, 5, 28),
            type_="industry",
            title="WWDC Keynote",
            ticker="AAPL",
        ),
        _fake_event(
            event_date=date(2026, 5, 27),
            type_="macro",
            title="CPI Release",
        ),
    ]

    smtp_instance = MagicMock()
    smtp_ctx = MagicMock()
    smtp_ctx.__enter__.return_value = smtp_instance
    smtp_ctx.__exit__.return_value = False

    with patch.object(email_dispatcher.smtplib, "SMTP", return_value=smtp_ctx):
        email_dispatcher.send_catalyst_digest(
            events=events,  # type: ignore[arg-type]
            as_of=date(2026, 5, 27),
            settings=cfg,
        )

    sent = smtp_instance.send_message.call_args.args[0]
    text_body, html_body = _extract_bodies(sent)
    # 今天 (the as_of day) prefix appears for May 27.
    assert "今天" in html_body
    # 明天 prefix appears for May 28.
    assert "明天" in html_body
    # Type labels translated to Chinese.
    assert "財報" in html_body
    assert "總經" in html_body
    assert "產業" in html_body
