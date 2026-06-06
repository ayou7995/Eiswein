"""Indicator base types + result contract.

Every indicator is a callable that takes a price DataFrame + a
:class:`IndicatorContext` and returns an immutable
:class:`IndicatorResult`. Results are persisted to ``daily_signal``
and rendered by the frontend as a scannable Pros/Cons list (NOT prose)
— see the ``UX Output Rules`` section in ``CLAUDE.md``.

Semver ``INDICATOR_VERSION`` is bumped whenever *any* formula or
threshold changes. Historical rows keep their stored version so the
API can distinguish "judged under v1.0.0 rules" from "judged under
v1.1.0 rules" without retroactively rewriting history.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    import pandas as pd

    from app.indicators.context import IndicatorContext

INDICATOR_VERSION: Final[str] = "1.3.1"


SignalToneLiteral = Literal["green", "yellow", "red", "neutral"]


class SignalTone:
    """Signal-color tone constants.

    Not a :class:`enum.Enum` because Pydantic frozen models serialize
    string-valued enums unpredictably across versions — persisting the
    raw string is simpler and mirrors the API contract (green/yellow/
    red/neutral bullets in the Pros/Cons UI).

    Values are ``Literal`` strings so mypy still enforces the closed
    set at every comparison / assignment site.
    """

    GREEN: Final[Literal["green"]] = "green"
    YELLOW: Final[Literal["yellow"]] = "yellow"
    RED: Final[Literal["red"]] = "red"
    NEUTRAL: Final[Literal["neutral"]] = "neutral"


INSUFFICIENT_DATA_LABEL = "資料不足"
COMPUTE_ERROR_LABEL = "計算錯誤"


class IndicatorResult(BaseModel):
    """Frozen result of a single indicator computation.

    ``value`` is the headline number (None if data insufficient).
    ``detail`` holds raw numeric breakdown for the expand-on-tap UI.
    ``data_sufficient=False`` forces signal=neutral per C10.

    ``data_as_of`` is the **actual date of the underlying data** that
    drove this result, which may lag the snapshot's trade_date when an
    upstream source (FRED, yfinance, watchlist breadth) hasn't published
    the latest bar yet. None means "unknown" — used by helpers that
    don't know their input window (insufficient/error fallbacks) and by
    historical rows from before the field was introduced. When ``data_as_of``
    is older than the snapshot ``date``, the UI surfaces a "資料截至 X"
    pill so the operator isn't fooled into believing today's number is
    actually today's data. See ``compute_ad_line`` for cross-source min:
    when an indicator reads multiple frames, ``data_as_of`` is the
    earliest "last update" across them — we're only as fresh as our
    worst-lagged input.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    value: float | None
    signal: SignalToneLiteral
    data_sufficient: bool
    short_label: str
    detail: dict[str, Any] = Field(default_factory=dict)
    computed_at: datetime
    indicator_version: str = INDICATOR_VERSION
    data_as_of: date | None = None


class Indicator(ABC):
    """Abstract pure-function indicator contract.

    Subclasses MUST NOT perform I/O; they consume the DataFrame + the
    indicator-scoped context. The same instance is reused across
    tickers (no state between calls).
    """

    name: str

    @abstractmethod
    def compute(
        self,
        frame: pd.DataFrame,
        context: IndicatorContext,
    ) -> IndicatorResult:
        """Compute indicator result for the supplied OHLCV frame."""


def insufficient_result(
    name: str,
    *,
    detail: dict[str, Any] | None = None,
    data_as_of: date | None = None,
) -> IndicatorResult:
    """Shortcut for ``data_sufficient=False`` results (C10).

    ``data_as_of`` is optional because some insufficient cases happen
    BEFORE we know the frame's last date (empty frame, missing column).
    When the indicator has a partial frame and knows the last date,
    passing it preserves honest provenance even on insufficient results.
    """
    return IndicatorResult(
        name=name,
        value=None,
        signal=SignalTone.NEUTRAL,
        data_sufficient=False,
        short_label=INSUFFICIENT_DATA_LABEL,
        detail=detail or {},
        computed_at=datetime.now(UTC),
        data_as_of=data_as_of,
    )


def error_result(name: str, *, error_class: str) -> IndicatorResult:
    """Shortcut for runtime-failure results — orchestrator uses this
    when an individual indicator raises (rule 14: graceful degradation).

    ``error_class`` is the exception type name only (e.g. "ValueError").
    The full exception message stays in structured logs — we don't want
    pandas/numpy internals (array shapes, index labels, path fragments)
    persisted to DailySignal.detail or leaked via the API response.
    """
    return IndicatorResult(
        name=name,
        value=None,
        signal=SignalTone.NEUTRAL,
        data_sufficient=False,
        short_label=COMPUTE_ERROR_LABEL,
        detail={"error_class": error_class},
        computed_at=datetime.now(UTC),
        data_as_of=None,
    )
