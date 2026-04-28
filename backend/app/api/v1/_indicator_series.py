"""Per-ticker 60-day indicator series builders (private helper).

The four supported indicators each have a series builder that takes an
OHLCV pandas DataFrame (already loaded from ``daily_price``) and emits
the JSON-ready response payload for the
``GET /ticker/{symbol}/indicator/{name}/series`` endpoint.

Why this lives next to the route module rather than under ``app/indicators``:
the indicator package contracts a ``DataFrame -> IndicatorResult``
single-snapshot shape. Stacking a 60-day rolling view on top would
muddy that contract. We reuse the underlying math primitives
(``sma``, ``wilder_rsi``, ``macd``, ``bollinger_bands`` from
``_helpers.py``) so the formulas are NOT reimplemented — only the
series-shaping logic lives here.

The Chinese summary strings follow the exact format strings called out
in the endpoint spec; they are short labels (Pros/Cons style), NOT
prose narration.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import date as DateType
from typing import TYPE_CHECKING, Final, Literal

import pandas as pd

from app.indicators._helpers import bollinger_bands, macd, sma, wilder_rsi

if TYPE_CHECKING:
    from app.db.models import DailyPrice


SERIES_DAYS: Final[int] = 60
_MA200_LOOKBACK: Final[int] = 200
_RSI_LENGTH: Final[int] = 14
_BB_LENGTH: Final[int] = 20
_MA50: Final[int] = 50
_MA200: Final[int] = 200
_GOLDEN_CROSS_LOOKBACK_DAYS: Final[int] = 10
_RSI_DELTA_DAYS: Final[int] = 14
_BB_BAND_WIDTH_LOOKBACK_DAYS: Final[int] = 5

IndicatorNameLiteral = Literal[
    "price_vs_ma", "rsi", "macd", "bollinger", "volume_anomaly", "relative_strength"
]

# Whitelist for the URL slug. The Bollinger indicator is named
# ``bollinger`` everywhere in the codebase (orchestrator registry, signals
# layer, DailySignal rows). The endpoint accepts that exact slug.
# ``volume_anomaly`` and ``relative_strength`` mirror their indicator
# module ``NAME`` constants verbatim.
SUPPORTED_INDICATORS: Final[frozenset[str]] = frozenset(
    {
        "price_vs_ma",
        "rsi",
        "macd",
        "bollinger",
        "volume_anomaly",
        "relative_strength",
    }
)

# How much trailing daily history is needed for each builder. Used for
# the route-level pre-flight 404 ("insufficient_history") so we don't
# even bother running the math when the data isn't there. Values match
# the inner contract: 60-day output window + the lookback the math
# primitive needs (e.g. 20-day rolling avg for volume_anomaly,
# (-60, 0) span for relative_strength's daily cumulative).
_VOLUME_LOOKBACK_BACK: Final[int] = 20
_RS_DAY_OFFSET: Final[int] = 60

VOLUME_ANOMALY_MIN_BARS: Final[int] = SERIES_DAYS + _VOLUME_LOOKBACK_BACK
RELATIVE_STRENGTH_MIN_BARS: Final[int] = SERIES_DAYS + 1


def build_close_frame(rows: Sequence[DailyPrice]) -> pd.DataFrame:
    """Build an OHLC DataFrame indexed by tz-aware DatetimeIndex.

    Rows are assumed sorted ascending by ``date`` (the repository
    contract). The DatetimeIndex is required for the weekly resample
    in the RSI series; we anchor at NY market timezone to match the
    convention used elsewhere (test fixtures, backfill).
    """
    if not rows:
        return pd.DataFrame()
    index = pd.DatetimeIndex([pd.Timestamp(r.date) for r in rows], tz="America/New_York")
    return pd.DataFrame(
        {
            "open": [float(r.open) for r in rows],
            "high": [float(r.high) for r in rows],
            "low": [float(r.low) for r in rows],
            "close": [float(r.close) for r in rows],
            "volume": [int(r.volume) for r in rows],
        },
        index=index,
    )


# --- Price vs MA ----------------------------------------------------------


def build_price_vs_ma_payload(
    symbol: str, frame: pd.DataFrame, days: int = SERIES_DAYS
) -> dict[str, object]:
    """Construct the ``price_vs_ma`` series + summary payload."""
    close = frame["close"].astype("float64")
    ma50_full = sma(close, _MA50)
    ma200_full = sma(close, _MA200)

    tail_close = close.iloc[-days:]
    tail_ma50 = ma50_full.iloc[-days:]
    tail_ma200 = ma200_full.iloc[-days:]

    series = [
        {
            "date": _index_to_date(idx),
            "price": _round_or_none(price),
            "ma50": _round_or_none(ma50),
            "ma200": _round_or_none(ma200),
        }
        for idx, price, ma50, ma200 in zip(
            tail_close.index, tail_close, tail_ma50, tail_ma200, strict=True
        )
    ]

    above_both_days = _consecutive_above_both(tail_close, tail_ma50, tail_ma200)
    cross_note = _detect_ma_cross(ma50_full, ma200_full, _GOLDEN_CROSS_LOOKBACK_DAYS)
    summary = _price_vs_ma_summary(
        latest_price=float(tail_close.iloc[-1]) if not _is_nan(tail_close.iloc[-1]) else None,
        latest_ma50=_safe_float(tail_ma50.iloc[-1]),
        latest_ma200=_safe_float(tail_ma200.iloc[-1]),
        above_both_days=above_both_days,
        cross_note=cross_note,
    )

    current_price = _safe_float(tail_close.iloc[-1])
    current_ma50 = _safe_float(tail_ma50.iloc[-1])
    current_ma200 = _safe_float(tail_ma200.iloc[-1])

    return {
        "symbol": symbol,
        "indicator": "price_vs_ma",
        "series": series,
        "summary_zh": summary,
        "current": {
            "price": _round_or_none(current_price),
            "ma50": _round_or_none(current_ma50),
            "ma200": _round_or_none(current_ma200),
            "above_both_days": above_both_days,
        },
    }


def _consecutive_above_both(close: pd.Series, ma50: pd.Series, ma200: pd.Series) -> int:
    """Walk the tail backwards; count consecutive days where price was
    strictly above BOTH MAs. Stops at the first violating day or NaN."""
    count = 0
    for i in range(len(close) - 1, -1, -1):
        c = close.iloc[i]
        m50 = ma50.iloc[i]
        m200 = ma200.iloc[i]
        if _is_nan(c) or _is_nan(m50) or _is_nan(m200):
            break
        if c > m50 and c > m200:
            count += 1
        else:
            break
    return count


def _detect_ma_cross(
    ma50: pd.Series, ma200: pd.Series, lookback_days: int
) -> Literal["golden", "death", "none"]:
    """Look back ``lookback_days`` for a sign change of (ma50 - ma200)."""
    diff = (ma50 - ma200).dropna()
    if len(diff) < 2:
        return "none"
    window = diff.iloc[-(lookback_days + 1) :]
    if len(window) < 2:
        return "none"
    for i in range(len(window) - 1, 0, -1):
        prev = window.iloc[i - 1]
        curr = window.iloc[i]
        if prev <= 0 < curr:
            return "golden"
        if prev >= 0 > curr:
            return "death"
    return "none"


def _price_vs_ma_summary(
    *,
    latest_price: float | None,
    latest_ma50: float | None,
    latest_ma200: float | None,
    above_both_days: int,
    cross_note: Literal["golden", "death", "none"],
) -> str:
    cross_label = {
        "golden": "近期黃金交叉",
        "death": "近期死亡交叉",
        "none": "無近期交叉",
    }[cross_note]
    if latest_price is None or latest_ma50 is None or latest_ma200 is None:
        return f"資料不足，{cross_label}"
    if latest_price > latest_ma50 and latest_price > latest_ma200:
        return f"站上 50/200MA 連續 {above_both_days} 天，{cross_label}"
    return f"未站穩 50/200MA，{cross_label}"


# --- RSI ------------------------------------------------------------------


def build_rsi_payload(
    symbol: str, frame: pd.DataFrame, days: int = SERIES_DAYS
) -> dict[str, object]:
    close = frame["close"].astype("float64")
    daily_full = wilder_rsi(close, _RSI_LENGTH)

    weekly_full = _weekly_rsi_carry_forward(close)

    tail_daily = daily_full.iloc[-days:]
    tail_weekly = weekly_full.reindex(tail_daily.index, method="ffill")

    series = [
        {
            "date": _index_to_date(idx),
            "daily": _round_or_none(daily),
            "weekly": _round_or_none(weekly),
        }
        for idx, daily, weekly in zip(tail_daily.index, tail_daily, tail_weekly, strict=True)
    ]

    current_daily = _safe_float(tail_daily.iloc[-1])
    current_weekly = _safe_float(tail_weekly.iloc[-1])
    zone = _rsi_zone(current_daily)
    delta_summary = _rsi_delta_phrase(tail_daily, _RSI_DELTA_DAYS)
    summary = _rsi_summary(zone=zone, delta_phrase=delta_summary)

    return {
        "symbol": symbol,
        "indicator": "rsi",
        "series": series,
        "summary_zh": summary,
        "current": {
            "daily": _round_or_none(current_daily),
            "weekly": _round_or_none(current_weekly),
            "zone": zone,
        },
        "thresholds": {"oversold": 30, "overbought": 70},
    }


def _weekly_rsi_carry_forward(close: pd.Series) -> pd.Series:
    """Friday-anchored weekly close → wilder_rsi → series indexed by
    weekly Friday timestamps. The caller forward-fills onto daily dates.
    """
    if close.empty:
        return pd.Series(dtype="float64")
    weekly_close = close.resample("W-FRI").last().dropna()
    if len(weekly_close) < _RSI_LENGTH + 1:
        return pd.Series(index=weekly_close.index, dtype="float64")
    return wilder_rsi(weekly_close, _RSI_LENGTH)


_RSIZone = Literal["oversold", "neutral_weak", "neutral_strong", "overbought", "unknown"]


def _rsi_zone(value: float | None) -> _RSIZone:
    if value is None:
        return "unknown"
    if value < 30:
        return "oversold"
    if value < 50:
        return "neutral_weak"
    if value <= 70:
        return "neutral_strong"
    return "overbought"


_ZONE_LABEL_ZH: Final[dict[_RSIZone, str]] = {
    "oversold": "超賣",
    "neutral_weak": "中性偏弱",
    "neutral_strong": "中性偏強",
    "overbought": "超買",
    "unknown": "資料不足",
}


def _rsi_delta_phrase(daily: pd.Series, lookback_days: int) -> str:
    cleaned = daily.dropna()
    if len(cleaned) < 2:
        return "持平"
    latest = float(cleaned.iloc[-1])
    if len(cleaned) <= lookback_days:
        prior = float(cleaned.iloc[0])
    else:
        prior = float(cleaned.iloc[-(lookback_days + 1)])
    delta = latest - prior
    if delta > 5:
        return f"{lookback_days} 天從 {prior:.0f} 上來"
    if delta < -5:
        return f"{lookback_days} 天從 {prior:.0f} 下來"
    return f"持平於 ~{latest:.0f}"


def _rsi_summary(*, zone: _RSIZone, delta_phrase: str) -> str:
    label = _ZONE_LABEL_ZH[zone]
    return f"日 RSI {label}，{delta_phrase}"


# --- MACD -----------------------------------------------------------------


def build_macd_payload(
    symbol: str, frame: pd.DataFrame, days: int = SERIES_DAYS
) -> dict[str, object]:
    close = frame["close"].astype("float64")
    macd_result = macd(close)
    macd_line = macd_result.macd_line
    signal_line = macd_result.signal_line
    histogram = macd_result.histogram

    tail_macd = macd_line.iloc[-days:]
    tail_signal = signal_line.iloc[-days:]
    tail_hist = histogram.iloc[-days:]

    series = [
        {
            "date": _index_to_date(idx),
            "macd": _round_or_none(m),
            "signal": _round_or_none(s),
            "histogram": _round_or_none(h),
        }
        for idx, m, s, h in zip(tail_macd.index, tail_macd, tail_signal, tail_hist, strict=True)
    ]

    last_cross, bars_since_cross = _last_cross_in_window(tail_macd, tail_signal)
    hist_streak = _histogram_streak(tail_hist)
    summary = _macd_summary(
        streak=hist_streak,
        last_cross=last_cross,
        bars_since_cross=bars_since_cross,
    )

    return {
        "symbol": symbol,
        "indicator": "macd",
        "series": series,
        "summary_zh": summary,
        "current": {
            "macd": _round_or_none(_safe_float(tail_macd.iloc[-1])),
            "signal": _round_or_none(_safe_float(tail_signal.iloc[-1])),
            "histogram": _round_or_none(_safe_float(tail_hist.iloc[-1])),
            "last_cross": last_cross,
            "bars_since_cross": bars_since_cross,
        },
    }


def _last_cross_in_window(
    macd_line: pd.Series, signal_line: pd.Series
) -> tuple[Literal["golden", "death"] | None, int | None]:
    """Find the most-recent sign change of (macd - signal) inside the
    60-day window. Returns ``(kind, bars_since)`` where bars_since is
    counted from the cross day to the latest day (0 = cross today)."""
    diff = (macd_line - signal_line).dropna()
    if len(diff) < 2:
        return None, None
    for i in range(len(diff) - 1, 0, -1):
        prev = diff.iloc[i - 1]
        curr = diff.iloc[i]
        bars = (len(diff) - 1) - i
        if prev <= 0 < curr:
            return "golden", bars
        if prev >= 0 > curr:
            return "death", bars
    return None, None


class _HistogramStreak:
    """Sign + length + expanding/shrinking flag for the current run of
    same-signed histogram values.
    """

    __slots__ = ("sign", "length", "expanding")

    def __init__(self, sign: int, length: int, expanding: bool) -> None:
        self.sign = sign
        self.length = length
        self.expanding = expanding


def _histogram_streak(hist: pd.Series) -> _HistogramStreak:
    cleaned = hist.dropna()
    if cleaned.empty:
        return _HistogramStreak(sign=0, length=0, expanding=False)
    last = float(cleaned.iloc[-1])
    sign = 1 if last > 0 else (-1 if last < 0 else 0)
    if sign == 0:
        return _HistogramStreak(sign=0, length=1, expanding=False)
    length = 1
    for i in range(len(cleaned) - 2, -1, -1):
        v = float(cleaned.iloc[i])
        if (sign > 0 and v > 0) or (sign < 0 and v < 0):
            length += 1
        else:
            break
    if len(cleaned) >= 2:
        prev = float(cleaned.iloc[-2])
        expanding = abs(last) > abs(prev)
    else:
        expanding = True
    return _HistogramStreak(sign=sign, length=length, expanding=expanding)


def _macd_summary(
    *,
    streak: _HistogramStreak,
    last_cross: Literal["golden", "death"] | None,
    bars_since_cross: int | None,
) -> str:
    if streak.sign > 0:
        head = (
            f"histogram 連 {streak.length} 天為正且擴張"
            if streak.expanding
            else f"histogram 連 {streak.length} 天為正但縮小"
        )
    elif streak.sign < 0:
        head = (
            f"histogram 連 {streak.length} 天為負且擴張"
            if streak.expanding
            else f"histogram 連 {streak.length} 天為負但縮小"
        )
    else:
        head = "histogram 為零"

    if last_cross == "golden" and bars_since_cross is not None:
        tail = f"，距上次黃金交叉 {bars_since_cross} 天"
    elif last_cross == "death" and bars_since_cross is not None:
        tail = f"，距上次死亡交叉 {bars_since_cross} 天"
    else:
        tail = "，60 日內無交叉"
    return head + tail


# --- Bollinger Bands ------------------------------------------------------


def build_bollinger_payload(
    symbol: str, frame: pd.DataFrame, days: int = SERIES_DAYS
) -> dict[str, object]:
    close = frame["close"].astype("float64")
    bands = bollinger_bands(close, length=_BB_LENGTH)

    tail_close = close.iloc[-days:]
    tail_upper = bands.upper.iloc[-days:]
    tail_middle = bands.middle.iloc[-days:]
    tail_lower = bands.lower.iloc[-days:]

    series = [
        {
            "date": _index_to_date(idx),
            "price": _round_or_none(price),
            "upper": _round_or_none(upper),
            "middle": _round_or_none(middle),
            "lower": _round_or_none(lower),
        }
        for idx, price, upper, middle, lower in zip(
            tail_close.index,
            tail_close,
            tail_upper,
            tail_middle,
            tail_lower,
            strict=True,
        )
    ]

    current_price = _safe_float(tail_close.iloc[-1])
    current_upper = _safe_float(tail_upper.iloc[-1])
    current_middle = _safe_float(tail_middle.iloc[-1])
    current_lower = _safe_float(tail_lower.iloc[-1])

    position = _bb_position(price=current_price, upper=current_upper, lower=current_lower)
    band_width = (
        current_upper - current_lower
        if current_upper is not None and current_lower is not None
        else None
    )
    band_width_5d_change = _bb_band_width_change(
        bands.upper, bands.lower, lookback_days=_BB_BAND_WIDTH_LOOKBACK_DAYS
    )

    summary = _bollinger_summary(position=position, band_width_change=band_width_5d_change)

    return {
        "symbol": symbol,
        "indicator": "bollinger",
        "series": series,
        "summary_zh": summary,
        "current": {
            "price": _round_or_none(current_price),
            "upper": _round_or_none(current_upper),
            "middle": _round_or_none(current_middle),
            "lower": _round_or_none(current_lower),
            "position": _round_or_none(position, ndigits=4),
            "band_width": _round_or_none(band_width),
            "band_width_5d_change": _round_or_none(band_width_5d_change),
        },
    }


def _bb_position(*, price: float | None, upper: float | None, lower: float | None) -> float | None:
    if price is None or upper is None or lower is None:
        return None
    width = upper - lower
    if width <= 0:
        return None
    return (price - lower) / width


def _bb_band_width_change(
    upper: pd.Series, lower: pd.Series, *, lookback_days: int
) -> float | None:
    width = (upper - lower).dropna()
    if len(width) < lookback_days + 1:
        return None
    return float(width.iloc[-1]) - float(width.iloc[-(lookback_days + 1)])


def _bollinger_summary(*, position: float | None, band_width_change: float | None) -> str:
    if position is None:
        head = "資料不足"
    elif position < 0:
        head = "跌破下軌"
    elif position < 0.2:
        head = f"位置 {position:.2f} 接近下軌"
    elif position < 0.4:
        head = f"位置 {position:.2f} 中軌下方"
    elif position < 0.6:
        head = f"位置 {position:.2f} 中軌附近"
    elif position < 0.8:
        head = f"位置 {position:.2f} 中軌上方"
    elif position <= 1.0:
        head = f"位置 {position:.2f} 接近上軌"
    else:
        head = "突破上軌"

    if band_width_change is None:
        tail = "，帶寬資料不足"
    elif band_width_change > 0.01:
        tail = "，5 天內帶寬擴張"
    elif band_width_change < -0.01:
        tail = "，5 天內帶寬收縮"
    else:
        tail = "，帶寬持平"
    return head + tail


# --- Volume anomaly -------------------------------------------------------


_VOLUME_WINDOW: Final[int] = 20
_VOLUME_5D_WINDOW: Final[int] = 5
_VOLUME_SPIKE_MULTIPLIER: Final[float] = 2.0
_VOLUME_TREND_LOW: Final[float] = 0.85
_VOLUME_TREND_HIGH: Final[float] = 1.15


def build_volume_anomaly_payload(
    symbol: str, frame: pd.DataFrame, days: int = SERIES_DAYS
) -> dict[str, object]:
    """Construct the ``volume_anomaly`` series + summary payload.

    Each row in the 60-day series carries the day's volume, the day's
    price-change %, and the **prior-20-day** rolling average volume —
    the same denominator the indicator uses (excludes today). The
    ``current`` block mirrors what :func:`compute_volume_anomaly`
    produces for the latest bar plus a ``five_day_avg_ratio`` summarising
    the most recent week of volume vs the 20-day baseline.
    """
    close = frame["close"].astype("float64")
    volume = frame["volume"].astype("float64")

    # Prior-20-day rolling mean (shift(1) excludes today, matching the
    # indicator's "prior 20 days" semantics so ``ratio = today / avg``
    # is consistent across endpoint and stored signal.
    avg_20 = volume.shift(1).rolling(_VOLUME_WINDOW, min_periods=_VOLUME_WINDOW).mean()
    ratio = volume / avg_20
    price_change_pct = close.pct_change() * 100.0

    tail_vol = volume.iloc[-days:]
    tail_avg = avg_20.iloc[-days:]
    tail_change = price_change_pct.iloc[-days:]

    series = [
        {
            "date": _index_to_date(idx),
            "volume": int(v) if not _is_nan(v) else 0,
            "price_change_pct": _round_or_none(chg, ndigits=4),
            "avg_volume_20d": _round_or_none(avg, ndigits=2),
        }
        for idx, v, chg, avg in zip(tail_vol.index, tail_vol, tail_change, tail_avg, strict=True)
    ]

    today_volume = float(tail_vol.iloc[-1])
    today_avg_20 = _safe_float(tail_avg.iloc[-1])
    today_ratio = today_volume / today_avg_20 if today_avg_20 and today_avg_20 > 0 else None
    spike = today_ratio is not None and today_ratio >= _VOLUME_SPIKE_MULTIPLIER

    five_day_avg_ratio = _five_day_avg_ratio(ratio)

    summary = _volume_anomaly_summary(
        today_ratio=today_ratio,
        five_day_avg_ratio=five_day_avg_ratio,
        spike=spike,
    )

    return {
        "symbol": symbol,
        "indicator": "volume_anomaly",
        "series": series,
        "summary_zh": summary,
        "current": {
            "today_volume": int(today_volume),
            "avg_volume_20d": _round_or_none(today_avg_20, ndigits=2),
            "ratio": _round_or_none(today_ratio, ndigits=4),
            "five_day_avg_ratio": _round_or_none(five_day_avg_ratio, ndigits=4),
            "spike": spike,
        },
    }


def _five_day_avg_ratio(ratio: pd.Series) -> float | None:
    cleaned = ratio.dropna()
    if cleaned.empty:
        return None
    tail = cleaned.iloc[-_VOLUME_5D_WINDOW:]
    if tail.empty:
        return None
    return float(tail.mean())


def _volume_anomaly_summary(
    *,
    today_ratio: float | None,
    five_day_avg_ratio: float | None,
    spike: bool,
) -> str:
    if today_ratio is None:
        return "資料不足"
    head = f"今日量 {today_ratio:.2f}×"
    if five_day_avg_ratio is None:
        body = ""
    else:
        if five_day_avg_ratio < _VOLUME_TREND_LOW:
            trend = "（萎縮中）"
        elif five_day_avg_ratio > _VOLUME_TREND_HIGH:
            trend = "（量增）"
        else:
            trend = "（持平）"
        body = f"，5 日均 {five_day_avg_ratio:.2f}×{trend}"
    base = f"{head}{body}"
    if spike:
        return f"⚠ 量能爆發 {base}"
    return base


# --- Relative strength ----------------------------------------------------


_RS_LEAD_THRESHOLD: Final[float] = 0.005


def build_relative_strength_payload(
    symbol: str,
    ticker_frame: pd.DataFrame,
    spx_frame: pd.DataFrame,
    days: int = SERIES_DAYS,
) -> dict[str, object]:
    """Construct the ``relative_strength`` series + summary payload.

    Both ticker and SPX are normalized to ``cum_return = (close_t /
    close_{-60}) - 1`` so day -60 is anchored at 0.0. We pairwise inner-
    join on the date index — SPY rarely has gaps that AAPL doesn't, but
    if it happens we drop the orphan day rather than fabricate a value.

    The ``current`` block carries both the 20-day return delta (matching
    the canonical :func:`compute_relative_strength` definition) and the
    60-day delta used by the summary string. The 20-day numbers are what
    the signal layer already classifies — exposing them here lets the UI
    round-trip with the daily_signal row without re-querying.
    """
    ticker_close = ticker_frame["close"].astype("float64")
    spx_close = spx_frame["close"].astype("float64")

    joined = pd.concat([ticker_close.rename("ticker"), spx_close.rename("spx")], axis=1).dropna()
    if len(joined) < min(days, SERIES_DAYS):
        return _relative_strength_insufficient(symbol)

    # The trailing 60 paired rows are the wire slice. Row 0 anchors at
    # 0.0 (cumulative return relative to itself); row 59 carries the
    # full-window return.
    tail = joined.iloc[-days:]
    base_ticker = float(tail["ticker"].iloc[0])
    base_spx = float(tail["spx"].iloc[0])

    series: list[dict[str, object]] = []
    for idx, t_close, s_close in zip(tail.index, tail["ticker"], tail["spx"], strict=True):
        t_ret = (float(t_close) / base_ticker) - 1.0 if base_ticker else 0.0
        s_ret = (float(s_close) / base_spx) - 1.0 if base_spx else 0.0
        series.append(
            {
                "date": _index_to_date(idx),
                "ticker_cum_return": _round_or_none(t_ret, ndigits=6),
                "spx_cum_return": _round_or_none(s_ret, ndigits=6),
                "diff": _round_or_none(t_ret - s_ret, ndigits=6),
            }
        )

    ticker_60d_return = (float(tail["ticker"].iloc[-1]) / base_ticker) - 1.0 if base_ticker else 0.0
    spx_60d_return = (float(tail["spx"].iloc[-1]) / base_spx) - 1.0 if base_spx else 0.0
    diff_60d = ticker_60d_return - spx_60d_return

    if len(joined) >= 21:
        prior_ticker_20 = float(joined["ticker"].iloc[-21])
        prior_spx_20 = float(joined["spx"].iloc[-21])
        ticker_20d_return = (
            (float(joined["ticker"].iloc[-1]) / prior_ticker_20) - 1.0 if prior_ticker_20 else 0.0
        )
        spx_20d_return = (
            (float(joined["spx"].iloc[-1]) / prior_spx_20) - 1.0 if prior_spx_20 else 0.0
        )
        diff_20d: float | None = ticker_20d_return - spx_20d_return
    else:
        ticker_20d_return = ticker_60d_return
        spx_20d_return = spx_60d_return
        diff_20d = None

    summary = _relative_strength_summary(diff_60d=diff_60d)

    return {
        "symbol": symbol,
        "indicator": "relative_strength",
        "series": series,
        "summary_zh": summary,
        "current": {
            "ticker_20d_return": _round_or_none(ticker_20d_return, ndigits=6),
            "spx_20d_return": _round_or_none(spx_20d_return, ndigits=6),
            "diff_20d": _round_or_none(diff_20d, ndigits=6),
            "ticker_60d_return": _round_or_none(ticker_60d_return, ndigits=6),
            "spx_60d_return": _round_or_none(spx_60d_return, ndigits=6),
            "diff_60d": _round_or_none(diff_60d, ndigits=6),
        },
    }


def _relative_strength_insufficient(symbol: str) -> dict[str, object]:
    # Belt-and-suspenders fallback. The route filters for
    # ``RELATIVE_STRENGTH_MIN_BARS`` upfront so callers shouldn't hit
    # this — but if they do, we still return a valid, frozen-pydantic-
    # compatible shape with empty series + zh "資料不足".
    return {
        "symbol": symbol,
        "indicator": "relative_strength",
        "series": [],
        "summary_zh": "資料不足",
        "current": {
            "ticker_20d_return": None,
            "spx_20d_return": None,
            "diff_20d": None,
            "ticker_60d_return": None,
            "spx_60d_return": None,
            "diff_60d": None,
        },
    }


def _relative_strength_summary(*, diff_60d: float) -> str:
    if diff_60d > _RS_LEAD_THRESHOLD:
        pct = diff_60d * 100.0
        return f"60 天領先大盤 +{pct:.1f}%"
    if diff_60d < -_RS_LEAD_THRESHOLD:
        pct = abs(diff_60d) * 100.0
        # U+2212 MINUS SIGN, per spec.
        return f"60 天落後大盤 \u2212{pct:.1f}%"
    return "60 天與大盤同步"


# --- shared helpers -------------------------------------------------------


def _index_to_date(value: object) -> DateType:
    """pandas Timestamp / datetime → ``date``. Pure type narrowing."""
    if isinstance(value, pd.Timestamp):
        return value.date()
    if hasattr(value, "date"):
        candidate = value.date()
        if isinstance(candidate, DateType):
            return candidate
    msg = f"unexpected index value type: {type(value)!r}"
    raise TypeError(msg)


def _is_nan(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, float):
        return math.isnan(value)
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _safe_float(value: object) -> float | None:
    if value is None or _is_nan(value):
        return None
    if isinstance(value, int | float):
        return float(value)
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _round_or_none(value: float | None, *, ndigits: int = 4) -> float | None:
    if value is None or _is_nan(value):
        return None
    return round(float(value), ndigits)
