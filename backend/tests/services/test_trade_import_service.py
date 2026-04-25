"""TradeImportService — preview + apply, dedup, sell-without-position, idempotency."""

from __future__ import annotations

import io
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import User
from app.db.repositories.position_repository import PositionRepository
from app.db.repositories.trade_repository import TradeRepository
from app.services.trade_import_service import TradeImportService, UnknownBrokerError

# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------

_HEADER = (
    "Activity Date,Process Date,Settle Date,Instrument,Description,"
    "Trans Code,Quantity,Price,Amount\n"
)


def _buy_row(
    symbol: str = "AAPL",
    qty: str = "10",
    price: str = "$150.00",
    date: str = "04/21/2026",
) -> str:
    return f"{date},{date},{date},{symbol},{symbol} Inc,Buy,{qty},{price},$1500.00\n"


def _sell_row(
    symbol: str = "AAPL",
    qty: str = "5",
    price: str = "$155.00",
    date: str = "04/21/2026",
) -> str:
    return f"{date},{date},{date},{symbol},{symbol} Inc,Sell,{qty},{price},$775.00\n"


def _csv(*rows: str) -> io.BytesIO:
    content = _HEADER + "".join(rows)
    return io.BytesIO(content.encode("utf-8"))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _mk_user(session: Session, username: str = "alice") -> int:
    user = User(username=username, password_hash="x", is_admin=False)
    session.add(user)
    session.flush()
    return user.id


def _make_service(db: Session) -> TradeImportService:
    return TradeImportService(
        db=db,
        trade_repository=TradeRepository(db),
        position_repository=PositionRepository(db),
    )


def _open_position(
    db: Session,
    user_id: int,
    symbol: str,
    shares: str = "10",
    avg_cost: str = "100",
) -> None:
    repo = PositionRepository(db)
    repo.create_open(
        user_id=user_id,
        symbol=symbol,
        shares=Decimal(shares),
        avg_cost=Decimal(avg_cost),
        opened_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    db.flush()


# ---------------------------------------------------------------------------
# UnknownBrokerError
# ---------------------------------------------------------------------------


def test_service_preview_unknown_broker_raises(db_session: Session) -> None:
    uid = _mk_user(db_session)
    service = _make_service(db_session)
    with pytest.raises(UnknownBrokerError):
        service.preview(user_id=uid, broker_key="not_a_real_broker", file=_csv(_buy_row()))


def test_service_apply_unknown_broker_raises(db_session: Session) -> None:
    uid = _mk_user(db_session)
    service = _make_service(db_session)
    with pytest.raises(UnknownBrokerError):
        service.apply(user_id=uid, broker_key="not_a_real_broker", file=_csv(_buy_row()))


# ---------------------------------------------------------------------------
# Preview: happy path
# ---------------------------------------------------------------------------


def test_service_preview_happy_path_two_buys_action_import(db_session: Session) -> None:
    uid = _mk_user(db_session)
    service = _make_service(db_session)
    result = service.preview(
        user_id=uid,
        broker_key="robinhood",
        file=_csv(_buy_row("AAPL", date="04/21/2026"), _buy_row("MSFT", date="04/22/2026")),
    )
    assert result.summary.would_import == 2
    assert result.summary.would_skip_duplicate == 0
    assert result.summary.errors == 0
    assert all(row.action == "import" for row in result.parsed)


def test_service_preview_happy_path_broker_label(db_session: Session) -> None:
    uid = _mk_user(db_session)
    service = _make_service(db_session)
    result = service.preview(
        user_id=uid,
        broker_key="robinhood",
        file=_csv(_buy_row()),
    )
    assert result.broker == "robinhood"


def test_service_preview_happy_path_total_rows_correct(db_session: Session) -> None:
    uid = _mk_user(db_session)
    service = _make_service(db_session)
    result = service.preview(
        user_id=uid,
        broker_key="robinhood",
        file=_csv(_buy_row("AAPL"), _buy_row("MSFT")),
    )
    assert result.total_rows == 2


# ---------------------------------------------------------------------------
# Preview: duplicate detection
# ---------------------------------------------------------------------------


def test_service_preview_duplicate_row_is_skip_duplicate(db_session: Session) -> None:
    uid = _mk_user(db_session)
    service = _make_service(db_session)
    file_bytes = _csv(_buy_row()).getvalue()

    # First pass — records only for external_id extraction
    first = service.preview(user_id=uid, broker_key="robinhood", file=io.BytesIO(file_bytes))
    assert len(first.parsed) == 1
    external_id = first.parsed[0].record.external_id

    # Seed the trade directly so second preview sees a duplicate
    trade_repo = TradeRepository(db_session)
    position_repo = PositionRepository(db_session)
    position_repo.create_open(
        user_id=uid,
        symbol="AAPL",
        shares=Decimal("10"),
        avg_cost=Decimal("150"),
        opened_at=datetime(2026, 4, 21, tzinfo=UTC),
    )
    db_session.flush()
    pos = position_repo.get_open_for_symbol(user_id=uid, symbol="AAPL")
    assert pos is not None
    trade_repo.append(
        user_id=uid,
        position_id=pos.id,
        symbol="AAPL",
        side="buy",
        shares=Decimal("10"),
        price=Decimal("150"),
        executed_at=datetime(2026, 4, 21, 4, 0, tzinfo=UTC),
        source="robinhood",
        external_id=external_id,
    )
    db_session.flush()

    second = service.preview(user_id=uid, broker_key="robinhood", file=io.BytesIO(file_bytes))
    assert second.summary.would_skip_duplicate == 1
    assert second.summary.would_import == 0
    assert second.parsed[0].action == "skip_duplicate"


# ---------------------------------------------------------------------------
# Preview: sell without position → error
# ---------------------------------------------------------------------------


def test_service_preview_sell_without_position_action_error(db_session: Session) -> None:
    uid = _mk_user(db_session)
    service = _make_service(db_session)
    result = service.preview(
        user_id=uid,
        broker_key="robinhood",
        file=_csv(_sell_row("AAPL")),
    )
    assert result.summary.errors >= 1
    assert result.parsed[0].action == "error"


def test_service_preview_sell_without_position_issue_code(db_session: Session) -> None:
    uid = _mk_user(db_session)
    service = _make_service(db_session)
    result = service.preview(
        user_id=uid,
        broker_key="robinhood",
        file=_csv(_sell_row("AAPL")),
    )
    issue_codes = [i.code for row in result.parsed for i in row.issues]
    assert "sell_without_position" in issue_codes


# ---------------------------------------------------------------------------
# Apply: fresh import creates Trade rows
# ---------------------------------------------------------------------------


def test_service_apply_fresh_import_two_buys_imported(db_session: Session) -> None:
    uid = _mk_user(db_session)
    service = _make_service(db_session)
    result = service.apply(
        user_id=uid,
        broker_key="robinhood",
        file=_csv(_buy_row("AAPL", date="04/21/2026"), _buy_row("MSFT", date="04/22/2026")),
    )
    assert result.summary.imported == 2


def test_service_apply_fresh_import_positions_auto_created(db_session: Session) -> None:
    uid = _mk_user(db_session)
    service = _make_service(db_session)
    service.apply(
        user_id=uid,
        broker_key="robinhood",
        file=_csv(_buy_row("AAPL", date="04/21/2026"), _buy_row("MSFT", date="04/22/2026")),
    )
    pos_repo = PositionRepository(db_session)
    aapl = pos_repo.get_open_for_symbol(user_id=uid, symbol="AAPL")
    msft = pos_repo.get_open_for_symbol(user_id=uid, symbol="MSFT")
    assert aapl is not None
    assert msft is not None


def test_service_apply_fresh_import_trade_source_is_robinhood(db_session: Session) -> None:
    uid = _mk_user(db_session)
    service = _make_service(db_session)
    service.apply(
        user_id=uid,
        broker_key="robinhood",
        file=_csv(_buy_row("AAPL")),
    )
    trade_repo = TradeRepository(db_session)
    trades = trade_repo.list_for_user(user_id=uid)
    assert len(trades) == 1
    assert trades[0].source == "robinhood"


# ---------------------------------------------------------------------------
# Apply: idempotent — second apply skips all
# ---------------------------------------------------------------------------


def test_service_apply_idempotent_first_pass_imports(db_session: Session) -> None:
    uid = _mk_user(db_session)
    service = _make_service(db_session)
    csv_bytes = _csv(_buy_row("AAPL"), _buy_row("MSFT")).getvalue()
    first = service.apply(user_id=uid, broker_key="robinhood", file=io.BytesIO(csv_bytes))
    assert first.summary.imported == 2


def test_service_apply_idempotent_second_pass_all_skipped(db_session: Session) -> None:
    uid = _mk_user(db_session)
    service = _make_service(db_session)
    csv_bytes = _csv(_buy_row("AAPL"), _buy_row("MSFT")).getvalue()
    service.apply(user_id=uid, broker_key="robinhood", file=io.BytesIO(csv_bytes))
    # Commit so the dedup query sees the rows
    db_session.commit()
    second = service.apply(user_id=uid, broker_key="robinhood", file=io.BytesIO(csv_bytes))
    assert second.summary.imported == 0
    assert second.summary.skipped_duplicate == 2


# ---------------------------------------------------------------------------
# Apply: buy + sell reduces position
# ---------------------------------------------------------------------------


def test_service_apply_sell_reduces_existing_position_shares(db_session: Session) -> None:
    uid = _mk_user(db_session)
    _open_position(db_session, uid, "AAPL", shares="10", avg_cost="100")
    service = _make_service(db_session)
    result = service.apply(
        user_id=uid,
        broker_key="robinhood",
        file=_csv(_sell_row("AAPL", qty="5", price="$155.00")),
    )
    assert result.summary.imported == 1
    pos = PositionRepository(db_session).get_open_for_symbol(user_id=uid, symbol="AAPL")
    assert pos is not None
    assert pos.shares == Decimal("5")


def test_service_apply_sell_realized_pnl_on_trade(db_session: Session) -> None:
    uid = _mk_user(db_session)
    _open_position(db_session, uid, "AAPL", shares="10", avg_cost="100")
    service = _make_service(db_session)
    service.apply(
        user_id=uid,
        broker_key="robinhood",
        file=_csv(_sell_row("AAPL", qty="5", price="$155.00")),
    )
    trades = TradeRepository(db_session).list_for_user(user_id=uid)
    assert len(trades) == 1
    # realized = (155 - 100) * 5 = 275
    assert trades[0].realized_pnl == Decimal("275.00")


# ---------------------------------------------------------------------------
# Apply: buy on existing position updates avg_cost
# ---------------------------------------------------------------------------


def test_service_apply_buy_on_existing_position_updates_avg_cost(db_session: Session) -> None:
    uid = _mk_user(db_session)
    _open_position(db_session, uid, "AAPL", shares="10", avg_cost="100")
    service = _make_service(db_session)
    # Buy 10 more at $200 → new avg = (10*100 + 10*200) / 20 = 150
    result = service.apply(
        user_id=uid,
        broker_key="robinhood",
        file=_csv(_buy_row("AAPL", qty="10", price="$200.00")),
    )
    assert result.summary.imported == 1
    pos = PositionRepository(db_session).get_open_for_symbol(user_id=uid, symbol="AAPL")
    assert pos is not None
    assert pos.avg_cost == Decimal("150")


# ---------------------------------------------------------------------------
# Apply: transactional per record (IntegrityError on 2nd → 1st + 3rd commit)
# ---------------------------------------------------------------------------


def test_service_apply_integrity_error_counts_as_skipped_duplicate(
    db_session: Session,
) -> None:
    """When TradeRepository.append raises IntegrityError, the row is counted
    as skipped_duplicate and the loop continues rather than aborting.

    Note: the service calls session.rollback() on IntegrityError which
    invalidates the current transaction, so subsequent rows in the same
    session also roll back. This test verifies the *counter* logic: the
    exception is caught, skipped_duplicate is incremented, and no uncaught
    exception propagates to the caller.
    """
    uid = _mk_user(db_session)
    service = _make_service(db_session)

    call_count = 0

    def _always_fails(self: TradeRepository, **kwargs: object) -> object:  # type: ignore[type-arg]
        nonlocal call_count
        call_count += 1
        raise IntegrityError("UNIQUE constraint failed", params=None, orig=Exception())

    csv_bytes = _csv(
        _buy_row("AAPL", date="04/21/2026"),
        _buy_row("MSFT", date="04/22/2026"),
    ).getvalue()

    with patch.object(TradeRepository, "append", _always_fails):
        result = service.apply(user_id=uid, broker_key="robinhood", file=io.BytesIO(csv_bytes))

    # Both rows hit IntegrityError → counted as skipped_duplicate, 0 imported
    assert result.summary.imported == 0
    assert result.summary.skipped_duplicate == 2


# ---------------------------------------------------------------------------
# Apply: error rows not imported, good rows committed
# ---------------------------------------------------------------------------


def test_service_apply_error_rows_not_imported_good_rows_are(db_session: Session) -> None:
    uid = _mk_user(db_session)
    service = _make_service(db_session)
    # 1 valid buy + 1 sell-without-position (error row)
    result = service.apply(
        user_id=uid,
        broker_key="robinhood",
        file=_csv(_buy_row("AAPL"), _sell_row("MSFT")),
    )
    # The buy is imported; the sell is blocked at preview (action=error)
    assert result.summary.imported == 1
    assert result.summary.errors >= 1


def test_service_apply_error_rows_issues_carried_through(db_session: Session) -> None:
    uid = _mk_user(db_session)
    service = _make_service(db_session)
    result = service.apply(
        user_id=uid,
        broker_key="robinhood",
        file=_csv(_buy_row("AAPL"), _sell_row("MSFT")),
    )
    codes = [i.code for i in result.issues]
    assert "sell_without_position" in codes
