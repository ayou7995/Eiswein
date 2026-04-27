"""Market-regime 60-day indicator series builders (private helper).

Companion to :mod:`_indicator_series` (per-ticker). Builds the JSON
payloads for ``GET /market/indicator/{name}/series`` covering the four
canonical market-regime indicators: ``spx_ma``, ``vix``, ``yield_spread``,
``ad_day``.

Each builder is a pure function: it takes already-loaded DB rows and the
trailing reference date, and returns a JSON-ready dict matching the
response schema. The route module performs all DB I/O and dispatches by
name. The Chinese summary strings follow the contract from the endpoint
spec (Pros/Cons-style short labels, NOT prose narration).

We reuse the underlying pandas primitives (``sma`` from indicator
helpers) and the canonical ``compute_*`` indicator functions for any
zone/classification logic that the API is contractually echoing — no
formula is reimplemented here.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import date as DateType
from typing import TYPE_CHECKING, Final, Literal

import pandas as pd

from app.indicators._helpers import percentile_in_window, sma

if TYPE_CHECKING:
    from app.db.models import DailyPrice, MacroIndicator


SERIES_DAYS: Final[int] = 60
_MA200: Final[int] = 200
_MA50: Final[int] = 50
_GOLDEN_CROSS_LOOKBACK_DAYS: Final[int] = 10
_VIX_TREND_WINDOW: Final[int] = 10
_VIX_TREND_NOTABLE_DELTA: Final[float] = 2.0
_VIX_PERCENTILE_WINDOW: Final[int] = 252
_AD_25D_WINDOW: Final[int] = 25
_AD_5D_WINDOW: Final[int] = 5

MarketIndicatorNameLiteral = Literal["spx_ma", "vix", "yield_spread", "ad_day", "dxy", "fed_rate"]

# Whitelist for the URL slug. Mirrors the NAME constants exported
# by ``app.indicators.market_regime`` (4) and ``app.indicators.macro`` (2);
# kept here so the route module doesn't have to import the indicator
# packages just for a string set. ``dxy`` / ``fed_rate`` are the
# canonical NAME constants — the FRED series IDs ``DTWEXBGS`` /
# ``FEDFUNDS`` live behind those slugs in the macro_indicator table.
SUPPORTED_MARKET_INDICATORS: Final[frozenset[str]] = frozenset(
    {"spx_ma", "vix", "yield_spread", "ad_day", "dxy", "fed_rate"}
)


# DXY uses the FRED ``DTWEXBGS`` series (Trade-Weighted USD Broad Index)
# as a proxy — see :mod:`app.indicators.macro.dxy` for the rationale.
DXY_MACRO_SERIES: Final[str] = "DTWEXBGS"
DXY_MA_WINDOW: Final[int] = 20
DXY_STREAK_WINDOW: Final[int] = 5
DXY_STREAK_NOTABLE: Final[int] = 3
# 60-day output window + 20-bar SMA warm-up. The route reads the full
# stored history (FRED is small) so this constant is only used for the
# pre-flight insufficient_history check.
DXY_MIN_BARS: Final[int] = SERIES_DAYS + DXY_MA_WINDOW

# FFR (FEDFUNDS) is published daily on FRED but rarely changes — we
# keep a 365 trading-day output window so the chart reads as a step
# function over a year of FOMC decisions.
FED_FUNDS_MACRO_SERIES: Final[str] = "FEDFUNDS"
FED_FUNDS_SERIES_DAYS: Final[int] = 365
FED_FUNDS_30D_WINDOW: Final[int] = 30


# --- shared loaders -------------------------------------------------------


def build_spy_frame(rows: Sequence[DailyPrice]) -> pd.DataFrame:
    """OHLCV frame indexed by tz-aware DatetimeIndex (NY).

    Same convention as :func:`_indicator_series.build_close_frame` so
    the two helpers stay symmetric.
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


def build_macro_value_series(rows: Sequence[MacroIndicator]) -> pd.Series:
    """Single-column ``value`` series indexed by date.

    Returns an empty Series when no rows. NaN-free input is the
    repository contract (FRED never returns NaN values).
    """
    if not rows:
        return pd.Series(dtype="float64")
    index = pd.DatetimeIndex([pd.Timestamp(r.date) for r in rows])
    return pd.Series([float(r.value) for r in rows], index=index, dtype="float64").sort_index()


# --- spx_ma ---------------------------------------------------------------


def build_spx_ma_payload(frame: pd.DataFrame, days: int = SERIES_DAYS) -> dict[str, object]:
    """SPX MA series payload — mirrors the per-ticker ``price_vs_ma`` shape
    sans the ``symbol`` field (market-level).

    ``days`` controls the trailing slice used for the chart payload. The
    50/200 MA series are computed over the full frame so the tail values
    are valid even when ``days`` is small.
    """
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
            "ma50": _round_or_none(ma50_v),
            "ma200": _round_or_none(ma200_v),
        }
        for idx, price, ma50_v, ma200_v in zip(
            tail_close.index, tail_close, tail_ma50, tail_ma200, strict=True
        )
    ]

    above_both_days = _consecutive_above_both(tail_close, tail_ma50, tail_ma200)
    cross_note = _detect_ma_cross(ma50_full, ma200_full, _GOLDEN_CROSS_LOOKBACK_DAYS)
    summary = _spx_ma_summary(
        latest_price=_safe_float(tail_close.iloc[-1]),
        latest_ma50=_safe_float(tail_ma50.iloc[-1]),
        latest_ma200=_safe_float(tail_ma200.iloc[-1]),
        above_both_days=above_both_days,
        cross_note=cross_note,
    )

    return {
        "indicator": "spx_ma",
        "series": series,
        "summary_zh": summary,
        "current": {
            "price": _round_or_none(_safe_float(tail_close.iloc[-1])),
            "ma50": _round_or_none(_safe_float(tail_ma50.iloc[-1])),
            "ma200": _round_or_none(_safe_float(tail_ma200.iloc[-1])),
            "above_both_days": above_both_days,
        },
    }


def _consecutive_above_both(close: pd.Series, ma50: pd.Series, ma200: pd.Series) -> int:
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


def _spx_ma_summary(
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
        "none": "無近期黃金/死亡交叉",
    }[cross_note]
    if latest_price is None or latest_ma50 is None or latest_ma200 is None:
        return f"資料不足，{cross_label}"
    if latest_price > latest_ma50 and latest_price > latest_ma200:
        return f"SPX 站上雙均 {above_both_days} 天，{cross_label}"
    return f"SPX 未站穩 50/200MA，{cross_label}"


# --- vix ------------------------------------------------------------------


VixZone = Literal["low", "normal", "elevated", "panic"]
_VIX_THRESHOLDS: Final[dict[str, float]] = {
    "low": 12.0,
    "normal_high": 20.0,
    "elevated_high": 30.0,
}


def build_vix_payload(value_series: pd.Series, days: int = SERIES_DAYS) -> dict[str, object]:
    cleaned = value_series.dropna()
    tail = cleaned.iloc[-days:]
    series = [
        {"date": _index_to_date(idx), "level": _round_or_none(level)}
        for idx, level in zip(tail.index, tail, strict=True)
    ]

    current_level = float(cleaned.iloc[-1])
    if len(cleaned) > _VIX_TREND_WINDOW:
        prior = float(cleaned.iloc[-(_VIX_TREND_WINDOW + 1)])
        ten_day_change: float | None = current_level - prior
    else:
        ten_day_change = None

    trend = _vix_trend(ten_day_change)
    zone = _vix_zone(current_level)
    percentile = percentile_in_window(cleaned, _VIX_PERCENTILE_WINDOW)
    summary = _vix_summary(
        level=current_level,
        zone=zone,
        ten_day_change=ten_day_change,
        percentile=percentile,
    )

    return {
        "indicator": "vix",
        "series": series,
        "summary_zh": summary,
        "current": {
            "level": _round_or_none(current_level, ndigits=2),
            "ten_day_change": _round_or_none(ten_day_change, ndigits=2),
            "trend": trend,
            "zone": zone,
            "percentile_1y": _round_or_none(percentile, ndigits=4),
        },
        "thresholds": {
            "low": int(_VIX_THRESHOLDS["low"]),
            "normal_high": int(_VIX_THRESHOLDS["normal_high"]),
            "elevated_high": int(_VIX_THRESHOLDS["elevated_high"]),
        },
    }


def _vix_zone(level: float) -> VixZone:
    if level < _VIX_THRESHOLDS["low"]:
        return "low"
    if level <= _VIX_THRESHOLDS["normal_high"]:
        return "normal"
    if level <= _VIX_THRESHOLDS["elevated_high"]:
        return "elevated"
    return "panic"


def _vix_trend(ten_day_change: float | None) -> Literal["rising", "falling", "flat", "unknown"]:
    if ten_day_change is None:
        return "unknown"
    if ten_day_change > 1.0:
        return "rising"
    if ten_day_change < -1.0:
        return "falling"
    return "flat"


_VIX_ZONE_LABEL_ZH: Final[dict[VixZone, str]] = {
    "low": "偏低區",
    "normal": "正常區",
    "elevated": "警戒區",
    "panic": "恐慌區",
}


def _vix_summary(
    *,
    level: float,
    zone: VixZone,
    ten_day_change: float | None,
    percentile: float | None,
) -> str:
    label = _VIX_ZONE_LABEL_ZH[zone]
    pct_phrase = (
        f"，過去 1 年 {int(round(percentile * 100))}% 百分位"
        if percentile is not None
        else "，百分位資料不足"
    )
    head = f"VIX {level:.1f} {label}{pct_phrase}"
    if ten_day_change is None:
        return head
    if ten_day_change > _VIX_TREND_NOTABLE_DELTA:
        return f"{head}，10 日上升 {ten_day_change:.1f}"
    if ten_day_change < -_VIX_TREND_NOTABLE_DELTA:
        # Negative sign already implied by "下降"; show absolute magnitude.
        return f"{head}，10 日下降 {abs(ten_day_change):.1f}"
    return head


# --- yield_spread ---------------------------------------------------------


def build_yield_spread_payload(
    ten_year: pd.Series,
    two_year: pd.Series,
    days: int = SERIES_DAYS,
) -> dict[str, object]:
    joined = pd.concat([ten_year.rename("ten"), two_year.rename("two")], axis=1).dropna()
    if joined.empty or len(joined) < min(days, SERIES_DAYS):
        return _yield_spread_insufficient()

    spread_full = joined["ten"] - joined["two"]
    tail = joined.iloc[-days:]
    spread_tail = spread_full.iloc[-days:]
    series = [
        {
            "date": _index_to_date(idx),
            "spread": _round_or_none(s, ndigits=4),
            "ten_year": _round_or_none(t, ndigits=4),
            "two_year": _round_or_none(two, ndigits=4),
        }
        for idx, s, t, two in zip(
            tail.index,
            spread_tail,
            tail["ten"],
            tail["two"],
            strict=True,
        )
    ]

    current_spread = float(spread_tail.iloc[-1])
    days_since, last_inversion_end = _yield_spread_inversion_window(spread_tail)

    summary = _yield_spread_summary(spread=current_spread, days_since_inversion=days_since)

    return {
        "indicator": "yield_spread",
        "series": series,
        "summary_zh": summary,
        "current": {
            "spread": _round_or_none(current_spread, ndigits=4),
            "ten_year": _round_or_none(float(tail["ten"].iloc[-1]), ndigits=4),
            "two_year": _round_or_none(float(tail["two"].iloc[-1]), ndigits=4),
            "days_since_inversion": days_since,
            "last_inversion_end": (
                last_inversion_end.isoformat() if last_inversion_end is not None else None
            ),
        },
    }


def _yield_spread_insufficient() -> dict[str, object]:
    # Returned only when the route's pre-flight slipped — the route
    # treats < SERIES_DAYS as 404, so this is belt-and-suspenders.
    return {
        "indicator": "yield_spread",
        "series": [],
        "summary_zh": "資料不足",
        "current": {
            "spread": None,
            "ten_year": None,
            "two_year": None,
            "days_since_inversion": None,
            "last_inversion_end": None,
        },
    }


def _yield_spread_inversion_window(
    spread_tail: pd.Series,
) -> tuple[int | None, DateType | None]:
    """Inversion bookkeeping over the 60-day window.

    * If currently inverted (spread < 0) → ``(0, None)``.
    * If positive after a recent inversion → days since the last inverted
      day, plus the date of the day spread crossed back above zero.
    * If never inverted in window → ``(None, None)``.
    """
    if spread_tail.empty:
        return None, None
    latest = float(spread_tail.iloc[-1])
    if latest < 0:
        return 0, None
    inverted_indices = [i for i in range(len(spread_tail)) if spread_tail.iloc[i] < 0]
    if not inverted_indices:
        return None, None
    last_inverted_idx = inverted_indices[-1]
    days_since = (len(spread_tail) - 1) - last_inverted_idx
    # The day spread "crossed back" is the first non-inverted day after
    # last_inverted_idx; in our trailing window that's last_inverted_idx + 1.
    cross_idx = last_inverted_idx + 1
    if cross_idx >= len(spread_tail):
        return days_since, None
    cross_date = _index_to_date(spread_tail.index[cross_idx])
    return days_since, cross_date


def _yield_spread_summary(*, spread: float, days_since_inversion: int | None) -> str:
    if spread < 0:
        return f"倒掛 {abs(spread):.2f}，警示"
    if days_since_inversion is None:
        return f"正斜率 +{spread:.2f}，無近期倒掛"
    return f"正斜率 +{spread:.2f}，{days_since_inversion} 天前脫離倒掛"


# --- ad_day ---------------------------------------------------------------


AdClassification = Literal["accum", "distrib", "neutral"]


def build_ad_day_payload(frame: pd.DataFrame, days: int = SERIES_DAYS) -> dict[str, object]:
    """Build A/D Day series + 25-day / 5-day aggregates.

    The per-day classification rule mirrors the indicator
    (:func:`compute_ad_day` in ``app.indicators.market_regime.ad_day``):
    a bar is ``accum`` when ``close > open`` AND ``volume > prev_volume``,
    ``distrib`` when ``close < open`` AND ``volume > prev_volume``, else
    ``neutral``. Identical operators, identical mask logic — kept inline
    here because the indicator function returns 25-day net counts, not
    per-day classifications.
    """
    # Need either ``days+1`` for the chart slice OR ``_AD_25D_WINDOW+1``
    # for the rolling 25-day net summary, whichever is larger. The 25-day
    # window is fixed by the indicator rule; ``days`` only affects what's
    # rendered in the chart.
    min_required = max(days, _AD_25D_WINDOW) + 1
    if frame.empty or len(frame) < min_required:
        return _ad_day_insufficient()

    open_ = frame["open"].astype("float64")
    high = frame["high"].astype("float64")
    low = frame["low"].astype("float64")
    close = frame["close"].astype("float64")
    volume = frame["volume"].astype("float64")
    prev_volume = volume.shift(1)

    is_up = close > open_
    is_down = close < open_
    volume_expanding = volume > prev_volume
    accum_mask = is_up & volume_expanding
    distrib_mask = is_down & volume_expanding

    classifications: list[AdClassification] = []
    for i in range(len(frame)):
        if bool(accum_mask.iloc[i]):
            classifications.append("accum")
        elif bool(distrib_mask.iloc[i]):
            classifications.append("distrib")
        else:
            classifications.append("neutral")

    spx_change_pct = ((close - open_) / open_) * 100.0
    volume_ratio = volume / prev_volume

    tail_idx = frame.index[-days:]
    tail_class = classifications[-days:]
    tail_change = spx_change_pct.iloc[-days:]
    tail_vol_ratio = volume_ratio.iloc[-days:]
    tail_open = open_.iloc[-days:]
    tail_high = high.iloc[-days:]
    tail_low = low.iloc[-days:]
    tail_close = close.iloc[-days:]
    tail_volume = volume.iloc[-days:]

    series = [
        {
            "date": _index_to_date(idx),
            "classification": cls,
            "spx_change": _round_or_none(chg, ndigits=2),
            "volume_ratio": _round_or_none(vr, ndigits=4),
            "open": _round_or_none(o, ndigits=2),
            "high": _round_or_none(h, ndigits=2),
            "low": _round_or_none(low_v, ndigits=2),
            "close": _round_or_none(c, ndigits=2),
            "volume": int(v),
        }
        for idx, cls, chg, vr, o, h, low_v, c, v in zip(
            tail_idx,
            tail_class,
            tail_change,
            tail_vol_ratio,
            tail_open,
            tail_high,
            tail_low,
            tail_close,
            tail_volume,
            strict=True,
        )
    ]

    accum_25 = sum(1 for c in classifications[-_AD_25D_WINDOW:] if c == "accum")
    distrib_25 = sum(1 for c in classifications[-_AD_25D_WINDOW:] if c == "distrib")
    accum_5 = sum(1 for c in classifications[-_AD_5D_WINDOW:] if c == "accum")
    distrib_5 = sum(1 for c in classifications[-_AD_5D_WINDOW:] if c == "distrib")
    net_25 = accum_25 - distrib_25
    net_5 = accum_5 - distrib_5

    summary = _ad_day_summary(
        accum_25=accum_25,
        distrib_25=distrib_25,
        net_25=net_25,
        accum_5=accum_5,
        distrib_5=distrib_5,
        net_5=net_5,
    )

    return {
        "indicator": "ad_day",
        "series": series,
        "summary_zh": summary,
        "current": {
            "accum_count_25d": accum_25,
            "distrib_count_25d": distrib_25,
            "net_25d": net_25,
            "accum_count_5d": accum_5,
            "distrib_count_5d": distrib_5,
            "net_5d": net_5,
        },
    }


def _ad_day_insufficient() -> dict[str, object]:
    return {
        "indicator": "ad_day",
        "series": [],
        "summary_zh": "資料不足",
        "current": {
            "accum_count_25d": 0,
            "distrib_count_25d": 0,
            "net_25d": 0,
            "accum_count_5d": 0,
            "distrib_count_5d": 0,
            "net_5d": 0,
        },
    }


def _ad_day_label(net: int) -> str:
    if net > 1:
        return "累積"
    if net < -1:
        return "出貨"
    return "中性"


def _ad_day_summary(
    *,
    accum_25: int,
    distrib_25: int,
    net_25: int,
    accum_5: int,
    distrib_5: int,
    net_5: int,
) -> str:
    label_25 = _ad_day_label(net_25)
    head = f"過去 25 天累積/出貨 {accum_25}:{distrib_25} {label_25}"
    label_5 = _ad_day_label(net_5)
    # Append the 5-day modifier only when it diverges from the 25-day
    # signal AND the 5-day window itself is non-trivial — otherwise the
    # baseline phrase already conveys the picture.
    if label_5 != label_25 and (accum_5 + distrib_5) > 0:
        return f"{head}，最近 5 天 {accum_5}:{distrib_5} {label_5}"
    return head


# --- dxy ------------------------------------------------------------------


def build_dxy_payload(value_series: pd.Series, days: int = SERIES_DAYS) -> dict[str, object]:
    """DXY series payload — emits 60 (level, ma20) rows + a streak
    summary that mirrors the canonical :func:`compute_dxy` semantics.

    The streak is computed off the 20-day SMA tail (``DXY_STREAK_WINDOW
    + 1`` rows of MA, diffs of consecutive values must be all-positive
    or all-negative for the streak to count). We surface the *actual*
    streak length the indicator detected — if every diff in the
    5-window is rising, ``streak_days = 5``; otherwise 0.
    """
    cleaned = value_series.dropna().sort_index()
    ma20_full = sma(cleaned, DXY_MA_WINDOW)

    tail_levels = cleaned.iloc[-days:]
    tail_ma20 = ma20_full.iloc[-days:]

    series = [
        {
            "date": _index_to_date(idx),
            "level": _round_or_none(level, ndigits=4),
            "ma20": _round_or_none(ma_v, ndigits=4),
        }
        for idx, level, ma_v in zip(tail_levels.index, tail_levels, tail_ma20, strict=True)
    ]

    current_level = _safe_float(tail_levels.iloc[-1])
    current_ma = _safe_float(tail_ma20.iloc[-1])

    streak_rising, streak_falling, streak_days = _dxy_streak(ma20_full)
    ma20_change_5d = _ma20_change(ma20_full, lookback=DXY_STREAK_WINDOW)

    summary = _dxy_summary(
        streak_rising=streak_rising,
        streak_falling=streak_falling,
        streak_days=streak_days,
        ma20_change_5d=ma20_change_5d,
    )

    return {
        "indicator": "dxy",
        "series": series,
        "summary_zh": summary,
        "current": {
            "level": _round_or_none(current_level, ndigits=4),
            "ma20": _round_or_none(current_ma, ndigits=4),
            "streak_rising": streak_rising,
            "streak_falling": streak_falling,
            "streak_days": streak_days,
            "ma20_change_5d": _round_or_none(ma20_change_5d, ndigits=4),
        },
    }


def _dxy_streak(ma20: pd.Series) -> tuple[bool, bool, int]:
    """Return (rising, falling, length) for the trailing MA20 streak.

    Walks backwards from the latest MA20 value collecting consecutive
    same-signed diffs. Diff-of-zero breaks the streak. ``length`` is
    the consecutive same-direction count, capped only by the available
    diffs. Both bool flags use the canonical-indicator threshold (5):
    ``streak_rising`` only true when all 5 trailing diffs are positive,
    matching :func:`compute_dxy` behaviour exactly.
    """
    cleaned = ma20.dropna()
    if len(cleaned) < DXY_STREAK_WINDOW + 1:
        return False, False, 0

    diffs = cleaned.diff().dropna()
    if diffs.empty:
        return False, False, 0

    last = float(diffs.iloc[-1])
    if last == 0:
        return False, False, 0
    sign = 1 if last > 0 else -1
    length = 1
    for i in range(len(diffs) - 2, -1, -1):
        v = float(diffs.iloc[i])
        if (sign > 0 and v > 0) or (sign < 0 and v < 0):
            length += 1
        else:
            break

    rising = sign > 0 and length >= DXY_STREAK_WINDOW
    falling = sign < 0 and length >= DXY_STREAK_WINDOW
    return rising, falling, length


def _ma20_change(ma20: pd.Series, *, lookback: int) -> float | None:
    cleaned = ma20.dropna()
    if len(cleaned) < lookback + 1:
        return None
    return float(cleaned.iloc[-1]) - float(cleaned.iloc[-(lookback + 1)])


def _dxy_summary(
    *,
    streak_rising: bool,
    streak_falling: bool,
    streak_days: int,
    ma20_change_5d: float | None,
) -> str:
    if streak_falling and streak_days >= DXY_STREAK_NOTABLE:
        head = "DXY 走弱（科技股順風）"
        direction = "連跌"
    elif streak_rising and streak_days >= DXY_STREAK_NOTABLE:
        head = "DXY 走強（科技股逆風）"
        direction = "連升"
    else:
        head = "DXY 持平"
        direction = "持平"

    change_str = f"{ma20_change_5d:+.2f}" if ma20_change_5d is not None else "0.00"
    detail = f"：MA20 {direction} {streak_days} 天，5 日變化 {change_str}"
    return f"{head}{detail}"


# --- fed_rate -------------------------------------------------------------


def build_fed_rate_payload(
    value_series: pd.Series,
    days: int = FED_FUNDS_SERIES_DAYS,
) -> dict[str, object]:
    """Forward-fill the FFR series across the trailing ``days`` calendar days.

    FRED's ``FEDFUNDS`` is monthly; the daily ``DFF`` is more granular
    but we follow the canonical indicator (which reads ``FEDFUNDS``).
    Step-chart semantics: every day inherits the most recent posted rate,
    so a chart over the year shows clear plateaus between FOMC decisions.
    The ``last_change_*`` fields surface the most recent date inside the
    chosen window where rate[d] != rate[d-1].
    """
    cleaned = value_series.dropna().sort_index()
    if cleaned.empty:
        return _fed_rate_insufficient()

    # Daily forward-fill onto a continuous date index covering the
    # trailing ``days`` (calendar). FRED forward-fills weekends, so the
    # calendar-day reindex preserves the level on every output row.
    end_ts = pd.Timestamp(cleaned.index[-1])
    start_ts = end_ts - pd.Timedelta(days=days - 1)
    full_idx = pd.date_range(start=start_ts, end=end_ts, freq="D")
    forward = cleaned.reindex(full_idx, method="ffill").dropna()

    series = [
        {
            "date": _index_to_date(idx),
            "rate": _round_or_none(level, ndigits=4),
        }
        for idx, level in zip(forward.index, forward, strict=True)
    ]

    current_rate = float(forward.iloc[-1])
    prior_30d_rate, delta_30d = _fed_rate_prior(forward, lookback=FED_FUNDS_30D_WINDOW)
    last_change_idx, last_change_dir = _fed_rate_last_change(forward)
    if last_change_idx is None:
        days_since_last_change: int | None = None
        last_change_date: DateType | None = None
    else:
        days_since_last_change = (len(forward) - 1) - last_change_idx
        last_change_date = _index_to_date(forward.index[last_change_idx])

    summary = _fed_rate_summary(
        current_rate=current_rate,
        delta_30d=delta_30d,
        days_since_last_change=days_since_last_change,
        last_change_direction=last_change_dir,
        last_change_date=last_change_date,
    )

    return {
        "indicator": "fed_rate",
        "series": series,
        "summary_zh": summary,
        "current": {
            "current_rate": _round_or_none(current_rate, ndigits=4),
            "prior_30d_rate": _round_or_none(prior_30d_rate, ndigits=4),
            "delta_30d": _round_or_none(delta_30d, ndigits=4),
            "days_since_last_change": days_since_last_change,
            "last_change_date": (
                last_change_date.isoformat() if last_change_date is not None else None
            ),
            "last_change_direction": last_change_dir,
        },
    }


def _fed_rate_insufficient() -> dict[str, object]:
    return {
        "indicator": "fed_rate",
        "series": [],
        "summary_zh": "資料不足",
        "current": {
            "current_rate": None,
            "prior_30d_rate": None,
            "delta_30d": None,
            "days_since_last_change": None,
            "last_change_date": None,
            "last_change_direction": None,
        },
    }


def _fed_rate_prior(forward: pd.Series, *, lookback: int) -> tuple[float, float]:
    """Return (prior_30d_rate, delta_30d) using forward-filled series.

    When the series is shorter than ``lookback + 1`` we fall back to
    the earliest available rate (delta becomes 0 if the series is
    fully flat — same outcome as a real flat year, no ambiguity).
    """
    if len(forward) <= lookback:
        prior = float(forward.iloc[0])
    else:
        prior = float(forward.iloc[-(lookback + 1)])
    current = float(forward.iloc[-1])
    return prior, current - prior


def _fed_rate_last_change(
    forward: pd.Series,
) -> tuple[int | None, Literal["hike", "cut"] | None]:
    """Find the most recent index where ``rate[d] != rate[d-1]``.

    Returns the index of day ``d`` (the new rate's first day) and
    whether that change was a hike or cut. ``(None, None)`` when the
    rate has been flat across the entire window.
    """
    if len(forward) < 2:
        return None, None
    diffs = forward.diff()
    nonzero = diffs[(diffs != 0) & (~diffs.isna())]
    if nonzero.empty:
        return None, None
    last_change_label = nonzero.index[-1]
    # ``Index.get_loc`` returns int for unique indices; we only ever call
    # this on a ``DatetimeIndex`` produced by reindex, which guarantees
    # uniqueness. The cast is a guard against mypy's broader return type
    # (``int | slice | ndarray``) — uniqueness is the precondition.
    last_change_idx = forward.index.get_loc(last_change_label)
    if not isinstance(last_change_idx, int):
        return None, None
    direction: Literal["hike", "cut"] = "hike" if float(nonzero.iloc[-1]) > 0 else "cut"
    return last_change_idx, direction


def _fed_rate_summary(
    *,
    current_rate: float,
    delta_30d: float,
    days_since_last_change: int | None,
    last_change_direction: Literal["hike", "cut"] | None,
    last_change_date: DateType | None,
) -> str:
    head = f"Fed 利率 {current_rate:.2f}%"

    if delta_30d == 0:
        if (
            days_since_last_change is None
            or last_change_direction is None
            or last_change_date is None
        ):
            return head
        label = "升息" if last_change_direction == "hike" else "降息"
        tail = (
            f"，已持平 {days_since_last_change} 天 " f"(上次{label} {last_change_date.isoformat()})"
        )
        return f"{head}{tail}"

    label = "升息" if delta_30d > 0 else "降息"
    return f"{head}，30 日內{label} {abs(delta_30d):.2f}%"


# --- shared helpers -------------------------------------------------------


def _index_to_date(value: object) -> DateType:
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
