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

from datetime import date
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


# --- ATR + ADX ----------------------------------------------------------
# Wilder's ADX system computes True Range, smoothes via the same
# alpha = 1/length recursive EMA used for RSI, and finally derives the
# directional movement (+DI, -DI) + the ADX itself. We hand-roll the
# math here for the same reasons as elsewhere in this module: stable
# pandas-only path, easy to audit against Wilder's "New Concepts in
# Technical Trading Systems" (1978).


class ADXResult(NamedTuple):
    """ADX system output: the three lines that drive both the ATR-based
    stop and the trend-strength signal."""

    atr: pd.Series
    plus_di: pd.Series
    minus_di: pd.Series
    adx: pd.Series


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """Wilder's True Range = max of three candidate ranges:

    1. today's H - L
    2. abs(today's H - yesterday's close)
    3. abs(today's L - yesterday's close)

    The previous-close terms capture gap-up / gap-down moves the simple
    H-L range would miss — which is exactly why ATR (smoothed TR) is
    more useful than ``high - low`` for stop sizing."""
    high = high.astype("float64")
    low = low.astype("float64")
    close = close.astype("float64")
    prev_close = close.shift(1)
    range_hl = high - low
    range_hc = (high - prev_close).abs()
    range_lc = (low - prev_close).abs()
    return cast(
        pd.Series,
        pd.concat([range_hl, range_hc, range_lc], axis=1).max(axis=1, skipna=False),
    )


def wilder_atr(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14) -> pd.Series:
    """ATR with Wilder's smoothing (alpha = 1/length).

    Seeds with the simple mean of the first ``length`` TR values so the
    series doesn't have to wait for the recursive EMA to converge."""
    tr = true_range(high, low, close)
    seed = tr.iloc[:length].mean()
    if pd.isna(seed):
        return pd.Series(index=tr.index, dtype="float64")
    out = [float("nan")] * (length - 1) + [float(seed)]
    alpha = 1.0 / length
    for i in range(length, len(tr)):
        prev = out[-1]
        current = float(tr.iloc[i])
        out.append((1 - alpha) * prev + alpha * current)
    return cast(pd.Series, pd.Series(out, index=tr.index, name="atr"))


def wilder_adx(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14) -> ADXResult:
    """Wilder's ADX + ATR + ±DI in one pass.

    Output series share the input index so callers can align with the
    underlying OHLCV frame. NaN-prefixed until the recursive smoothing
    has had ``length`` bars of input."""
    high = high.astype("float64")
    low = low.astype("float64")
    close = close.astype("float64")

    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = pd.Series(0.0, index=high.index, name="+DM")
    minus_dm = pd.Series(0.0, index=high.index, name="-DM")
    plus_dm[(up_move > down_move) & (up_move > 0)] = up_move
    minus_dm[(down_move > up_move) & (down_move > 0)] = down_move

    tr = true_range(high, low, close)

    # Wilder smoothing on TR / +DM / -DM via the same recursive 1/length EMA.
    def _smooth(series: pd.Series) -> pd.Series:
        seed = series.iloc[:length].sum()
        if pd.isna(seed):
            return pd.Series(index=series.index, dtype="float64")
        out = [float("nan")] * (length - 1) + [float(seed)]
        for i in range(length, len(series)):
            prev = out[-1]
            out.append(prev - prev / length + float(series.iloc[i]))
        return cast(pd.Series, pd.Series(out, index=series.index))

    tr_smoothed = _smooth(tr)
    plus_dm_smoothed = _smooth(plus_dm)
    minus_dm_smoothed = _smooth(minus_dm)

    plus_di = 100.0 * (plus_dm_smoothed / tr_smoothed)
    minus_di = 100.0 * (minus_dm_smoothed / tr_smoothed)
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)

    # ADX is the Wilder EMA of DX itself. Seed with the first ``length``
    # DX values' simple mean.
    dx_valid = dx.dropna()
    if len(dx_valid) < length:
        adx = pd.Series(index=dx.index, dtype="float64")
    else:
        first_valid_pos = dx.index.get_loc(dx_valid.index[0])
        seed_pos = int(first_valid_pos) + length - 1
        if seed_pos >= len(dx):
            adx_values: list[float] = [float("nan")] * len(dx)
        else:
            seed_value = float(dx.iloc[int(first_valid_pos) : seed_pos + 1].mean())
            adx_values = [float("nan")] * seed_pos + [seed_value]
            alpha = 1.0 / length
            for i in range(seed_pos + 1, len(dx)):
                prev = adx_values[-1]
                current = float(dx.iloc[i]) if not pd.isna(dx.iloc[i]) else prev
                adx_values.append((1 - alpha) * prev + alpha * current)
        adx = pd.Series(adx_values, index=dx.index, name="adx")

    # ATR == TR EMA (Wilder smoothing produces the same value via /length
    # divisor) — re-use the running smoothed TR.
    atr = tr_smoothed / length

    return ADXResult(atr=atr, plus_di=plus_di, minus_di=minus_di, adx=adx)


class KeltnerResult(NamedTuple):
    upper: pd.Series
    middle: pd.Series
    lower: pd.Series


def keltner_channels(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    *,
    length: int = 20,
    atr_mult: float = 1.5,
) -> KeltnerResult:
    """Keltner Channels: EMA(close, length) ± atr_mult × ATR(length).

    Chester Keltner's 1960 formulation (re-popularised by Linda Bradford
    Raschke). Used here as the TTM Squeeze's outer envelope — when
    Bollinger Bands compress *inside* Keltner Channels, volatility is
    coiled and a breakout is statistically imminent.
    """
    close_f = close.astype("float64")
    middle = close_f.ewm(span=length, adjust=False).mean()
    atr = wilder_atr(high, low, close, length=length)
    upper = middle + atr_mult * atr
    lower = middle - atr_mult * atr
    return KeltnerResult(upper=upper, middle=middle, lower=lower)


def linreg_slope(series: pd.Series, *, length: int) -> pd.Series:
    """Rolling ``length``-period linear regression slope.

    Output is the slope coefficient of an OLS fit y = a + b·x where
    x is the bar index 0..length-1 and y is the trailing ``length``
    values of the input. Used by TTM Squeeze to read a smooth momentum
    histogram off the de-midpoint'd close.
    """
    x = np.arange(length, dtype=float)
    x_mean = x.mean()
    x_var = float(((x - x_mean) ** 2).sum())

    def _slope(window: np.ndarray[tuple[int, ...], np.dtype[np.float64]]) -> float:
        y_mean = window.mean()
        return float(((x - x_mean) * (window - y_mean)).sum() / x_var)

    return cast(
        pd.Series,
        series.astype("float64").rolling(length, min_periods=length).apply(_slope, raw=True),
    )


def frame_as_of(frame: pd.DataFrame | None) -> date | None:
    """Return the date of the last row in ``frame``, or None if empty.

    Centralised here so every compute function uses the same convention:
    "the data this indicator just consumed is as fresh as the last
    row's index date." Combined with ``min`` across multiple frames it
    composes naturally for cross-source indicators (relative_strength,
    rsp_spy, hyg_ief, vix_term) — we're only as fresh as our
    worst-lagged input.
    """
    if frame is None or len(frame) == 0:
        return None
    last_idx = frame.index[-1]
    if hasattr(last_idx, "date"):
        result = last_idx.date()
        if isinstance(result, date):
            return result
    return None


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
