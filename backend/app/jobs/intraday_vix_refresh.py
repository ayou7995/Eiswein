"""Intraday VIX / VIX3M refresh — fills the FRED publication lag (Phase 6).

FRED publishes daily series like VIXCLS / VXVCLS at T+1 trading morning,
so on Wed 11am ET the latest FRED-served VIX is Tue's close. Operators
checking Eiswein during a midday selloff see "VIX 15.4" when the
actual real-time tape might be 22. This job patches that gap.

Plan:
* Runs every 15 minutes during NYSE market hours (09:30-16:30 ET Mon-Fri).
* Pulls the latest 5-minute bar for ``^VIX`` and ``^VIX3M`` via yfinance
  (free, no signup, real-time during market hours within ~15-min Yahoo
  delay).
* UPSERTs the close into ``macro_indicator`` under the same ``VIXCLS`` /
  ``VXVCLS`` series_ids FRED uses. The conflict-overwrite is intentional:
  next morning's FRED daily_update will UPSERT the official close which
  silently replaces our intraday read with the canonical value.
* Outside market hours the job is a no-op. We skip rather than refuse —
  APScheduler can fire near the boundary and we don't want the misfire-
  grace window to log false errors.

Why this is safe to overwrite:
* The intraday close at 16:00 ET ≈ Yahoo's published daily close
  ≈ tomorrow's FRED VIXCLS. The values converge.
* The ``data_as_of`` provenance contract (Phase data_as_of) does the
  right thing automatically — the indicator reports the date of whatever
  bar it last consumed, which is now today's intraday bar during market
  hours and yesterday's after-close until FRED publishes.
"""

from __future__ import annotations

from datetime import datetime, time
from decimal import Decimal
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import structlog

from app.db.repositories.macro_repository import MacroRepository, MacroRow

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

    from app.datasources.yfinance_source import YFinanceSource

logger = structlog.get_logger("eiswein.jobs.intraday_vix_refresh")

# yfinance index symbols → FRED series_ids we UPSERT into. Keeping the
# write target as the FRED ID means the rest of the system (indicators,
# series builders) never has to know there's an alternative source.
_SYMBOL_TO_SERIES: dict[str, str] = {
    "^VIX": "VIXCLS",
    "^VIX3M": "VXVCLS",
}

_NY = ZoneInfo("America/New_York")
_MARKET_OPEN = time(9, 30)
# Extended 30 minutes past close so the final session bar (often
# delayed-published at ~16:15 ET) gets captured.
_MARKET_CLOSE = time(16, 30)


def _is_market_hours(now: datetime) -> bool:
    """True if ``now`` is within NYSE market hours (Mon-Fri 9:30-16:30 ET).

    Holidays would still trigger the run; yfinance simply returns no
    new intraday bar on a closed-market day, so the result is a no-op
    UPSERT (same value written back). Not worth the extra dependency on
    a market-calendar lookup for that edge case.
    """
    et_now = now.astimezone(_NY)
    if et_now.weekday() >= 5:
        return False
    et_time = et_now.time()
    return _MARKET_OPEN <= et_time <= _MARKET_CLOSE


async def run(
    *,
    session_factory: sessionmaker[Session],
    data_source: YFinanceSource,
) -> None:
    now = datetime.now(_NY)
    if not _is_market_hours(now):
        logger.debug("intraday_vix_skipped_off_hours", now_et=now.isoformat())
        return

    latest = await data_source.fetch_intraday_last(list(_SYMBOL_TO_SERIES.keys()))
    rows: list[MacroRow] = []
    written: list[dict[str, str | float]] = []
    for symbol, series_id in _SYMBOL_TO_SERIES.items():
        bar = latest.get(symbol)
        if bar is None:
            logger.info("intraday_vix_no_bar", symbol=symbol)
            continue
        bar_date, close = bar
        rows.append(
            MacroRow(series_id=series_id, date=bar_date, value=Decimal(str(close)))
        )
        written.append(
            {"series_id": series_id, "date": bar_date.isoformat(), "value": close}
        )

    if not rows:
        logger.warning("intraday_vix_no_data", symbols=list(_SYMBOL_TO_SERIES))
        return

    with session_factory() as session:
        MacroRepository(session).upsert_many(rows)
        session.commit()

    logger.info("intraday_vix_refreshed", rows=written)
