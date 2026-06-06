"""Backfill v2 Phase 2/3/4 indicators into the daily_signal table.

The orchestrator gained ADX / ATR / TTM Squeeze / CHO / SPX ADX /
VIX Term / AD Line over Phases 2-4. ``daily_update`` writes a row for
each of them every day going forward, but past days only have the
pre-Phase-2 indicators on file. Future historical analyses
(``GET /history/signal-accuracy``, hypothetical backtest screens, etc.)
will see "missing rows" for those dates.

This script walks the last N trading days for every (symbol x indicator)
combination, recomputes the indicator from the stored DailyPrice +
MacroIndicator history, and UPSERTs the result into ``daily_signal``.
Existing rows are overwritten so it's safe to re-run.

Usage::

    cd backend
    .venv/bin/python ../scripts/backfill_new_indicators.py --days 90

The script reuses ``compute_and_persist_market_regime`` /
``compute_and_persist`` from ``app.ingestion.indicators`` so the math
path matches the live daily_update exactly. The only difference is the
date loop — we walk from (today - N) forward to today.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pandas_market_calendars as mcal
import structlog

# Allow ``python scripts/backfill_new_indicators.py`` from the repo root —
# without the path tweak the script can't import the ``app`` package
# because Python's import system doesn't know about ``backend/``.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_BACKEND = _REPO_ROOT / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from sqlalchemy import create_engine  # noqa: E402

from app.db.database import build_session_factory  # noqa: E402
from app.db.repositories.watchlist_repository import (  # noqa: E402
    WatchlistRepository,
)
from app.ingestion.indicators import (  # noqa: E402
    build_context,
    compute_and_persist,
    compute_and_persist_market_regime,
)

logger = structlog.get_logger("eiswein.scripts.backfill")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--days",
        type=int,
        default=90,
        help="Calendar days back from today to walk. Default: 90.",
    )
    p.add_argument(
        "--database-url",
        default="sqlite:///./data/eiswein_dev.db",
        help="SQLAlchemy URL. Default uses the dev SQLite DB.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Walk dates + log progress without writing.",
    )
    return p.parse_args()


def _trading_dates(end: date, days: int) -> list[date]:
    """Yield NYSE trading dates between ``end - days`` and ``end`` inclusive.

    Reused from the existing market_calendar utility — pandas_market_calendars
    handles weekends + US holidays the same way daily_update does.
    """
    cal = mcal.get_calendar("NYSE")
    start = end - timedelta(days=days)
    schedule = cal.schedule(start_date=start, end_date=end)
    return [pd.Timestamp(idx).date() for idx in schedule.index]


def main() -> int:
    args = _parse_args()
    engine = create_engine(args.database_url)
    session_factory = build_session_factory(engine)

    today = date.today()
    dates = _trading_dates(today, args.days)
    if not dates:
        logger.warning("backfill_no_trading_days", days=args.days)
        return 0

    logger.info(
        "backfill_start",
        days=args.days,
        date_range=(dates[0].isoformat(), dates[-1].isoformat()),
        trading_days=len(dates),
        dry_run=args.dry_run,
    )

    with session_factory() as session:
        symbols = list(
            WatchlistRepository(session).distinct_symbols_across_users()
        )
    if not symbols:
        logger.warning("backfill_empty_watchlist")
        return 0

    logger.info("backfill_universe", symbol_count=len(symbols))

    persisted_market = 0
    persisted_ticker = 0
    for trade_date in dates:
        with session_factory() as session:
            ctx = build_context(db=session, today=trade_date)
            if args.dry_run:
                logger.info(
                    "backfill_dry_run_date",
                    date=trade_date.isoformat(),
                    spx_bars=0 if ctx.spx_frame is None else len(ctx.spx_frame),
                    macro_series=list(ctx.macro_frames.keys()),
                )
                continue
            try:
                compute_and_persist_market_regime(
                    trade_date, db=session, context=ctx
                )
                persisted_market += 1
            except Exception as exc:
                logger.warning(
                    "backfill_market_regime_failed",
                    date=trade_date.isoformat(),
                    error=str(exc),
                )

            for symbol in symbols:
                try:
                    compute_and_persist(
                        symbol, trade_date, db=session, context=ctx
                    )
                    persisted_ticker += 1
                except Exception as exc:
                    logger.warning(
                        "backfill_ticker_failed",
                        date=trade_date.isoformat(),
                        symbol=symbol,
                        error=str(exc),
                    )
            session.commit()

    logger.info(
        "backfill_done",
        market_dates=persisted_market,
        ticker_writes=persisted_ticker,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
