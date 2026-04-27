"""Shared helpers for indicator modules (rule 7: DRY).

Wilder's RSI, MACD, Bollinger formulas are implemented here as pure
pandas operations. We hand-roll rather than depending on ``pandas_ta``
because (a) its 0.3.x release is abandoned and imports the removed
``numpy.NaN`` symbol, breaking under numpy>=2, and (b) these formulas
are short and standard enough that a local implementation is easier
to audit than a shimmed third-party one. Staff-review constraint C2
requires "Wilder's smoothing" for RSI — that's implemented explicitly
below via recursive EMA.
"""

from __future__ import annotations

from typing import NamedTuple, cast

import numpy as np
import pandas as pd


class MACDResult(NamedTuple):
    macd_line: pd.Series
    signal_line: pd.Series
    histogram: pd.Series


class BollingerResult(NamedTuple):
    upper: pd.Series
    middle: pd.Series
    lower: pd.Series


def wilder_rsi(close: pd.Series, length: int = 14) -> pd.Series:
    """RSI(14) using Wilder's smoothing — α = 1/length.

    Implementation mirrors the canonical Welles Wilder 1978 formulation
    (see *New Concepts in Technical Trading Systems*): the first value
    is a simple average of the first ``length`` gains/losses, and each
    subsequent value is recursively smoothed by
    ``new = (prev * (length-1) + current) / length``.

    ``pandas.Series.ewm(alpha=1/length, adjust=False)`` produces
    exactly this when the first observation of the window is treated
    as the initial value.
    """
    if close.empty or len(close) < length + 1:
        return pd.Series([float("nan")] * len(close), index=close.index, dtype="float64")

    delta = close.astype("float64").diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)

    avg_gain = gain.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()
    avg_loss = loss.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()

    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    # When avg_loss is 0 and avg_gain > 0, RSI is conventionally 100.
    rsi = rsi.where(avg_loss != 0.0, 100.0)
    # When both avg_gain and avg_loss are 0 (flat series), RSI undefined → 50.
    flat = (avg_gain == 0.0) & (avg_loss == 0.0)
    rsi = rsi.where(~flat, 50.0)
    return cast(pd.Series, rsi)


def macd(
    close: pd.Series,
    *,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> MACDResult:
    """Standard MACD (12, 26, 9)."""
    close_f = close.astype("float64")
    ema_fast = close_f.ewm(span=fast, adjust=False).mean()
    ema_slow = close_f.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return MACDResult(macd_line=macd_line, signal_line=signal_line, histogram=histogram)


def bollinger_bands(
    close: pd.Series,
    *,
    length: int = 20,
    std_mult: float = 2.0,
) -> BollingerResult:
    """Bollinger Bands (20-period, 2σ)."""
    close_f = close.astype("float64")
    middle = close_f.rolling(length, min_periods=length).mean()
    # ddof=0 to match TradingView's population-σ convention.
    std = close_f.rolling(length, min_periods=length).std(ddof=0)
    upper = middle + std_mult * std
    lower = middle - std_mult * std
    return BollingerResult(upper=upper, middle=middle, lower=lower)


def sma(series: pd.Series, length: int) -> pd.Series:
    return cast(pd.Series, series.astype("float64").rolling(length, min_periods=length).mean())


def last_float(series: pd.Series) -> float | None:
    """Return the last non-NaN value as a plain float, else None."""
    if series.empty:
        return None
    cleaned = series.dropna()
    if cleaned.empty:
        return None
    return float(cleaned.iloc[-1])


def last_two_floats(series: pd.Series) -> tuple[float, float] | None:
    """Return the last two non-NaN values, or None if not available."""
    if series.empty:
        return None
    cleaned = series.dropna()
    if len(cleaned) < 2:
        return None
    return (float(cleaned.iloc[-2]), float(cleaned.iloc[-1]))


def percentile_in_window(series: pd.Series, window: int) -> float | None:
    """Where the latest value ranks among the trailing ``window`` observations.

    Inclusive: ranks ``<=`` latest, so the most-recent point counts itself
    and a fresh all-time-high yields 1.0 (matches user intuition that "the
    highest in the year" is the 100th percentile).
    """
    cleaned = series.dropna()
    if cleaned.empty:
        return None
    tail = cleaned.iloc[-window:]
    if tail.empty:
        return None
    latest = float(tail.iloc[-1])
    rank = float((tail <= latest).sum())
    return rank / float(len(tail))


def detect_ma_crosses(
    short_ma: pd.Series,
    long_ma: pd.Series,
    lookback: int = 10,
) -> tuple[bool, bool]:
    """Detect bullish/bearish MA cross within the last ``lookback`` bars.

    Returns ``(golden_cross, death_cross)``. Used by both the SPX market
    regime indicator and per-ticker price-vs-MA — same definition,
    moved here so the formula has a single home.
    """
    joined = short_ma.to_frame("s").join(long_ma.to_frame("l"), how="inner").dropna()
    if len(joined) < 2:
        return False, False
    joined = joined.tail(lookback + 1)
    if len(joined) < 2:
        return False, False
    diff = joined["s"] - joined["l"]
    bullish = (diff.shift(1) <= 0) & (diff > 0)
    bearish = (diff.shift(1) >= 0) & (diff < 0)
    return bool(bullish.any()), bool(bearish.any())
