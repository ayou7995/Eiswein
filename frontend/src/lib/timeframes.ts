// Display layer for the indicator timeframe chip. Backend
// (`app/indicators/timeframes.py`) is the single source of truth for
// the mapping; this module just renders short/mid/long.

export type Timeframe = 'short' | 'mid' | 'long';

interface TimeframeStyle {
  label: string;
  className: string;
  ariaLabel: string;
}

export const TIMEFRAME_STYLE: Record<Timeframe, TimeframeStyle> = {
  short: {
    label: '短期',
    className: 'border-sky-500/40 bg-sky-500/10 text-sky-300',
    ariaLabel: '短期訊號',
  },
  mid: {
    label: '中期',
    className: 'border-violet-500/40 bg-violet-500/10 text-violet-300',
    ariaLabel: '中期訊號',
  },
  long: {
    label: '長期',
    className: 'border-teal-500/40 bg-teal-500/10 text-teal-300',
    ariaLabel: '長期訊號',
  },
};

// Mirror of backend ``app/indicators/timeframes.py::INDICATOR_TIMEFRAMES``.
// Authoritative source is the backend (and the API ships ``timeframe`` on
// every ProsConsItem); this map exists for components that render an
// indicator row directly without a ProsConsItem in hand — e.g. the
// per-ticker IndicatorRow and the MarketRegimeIndicatorList.
export const INDICATOR_TIMEFRAMES: Record<string, Timeframe> = {
  price_vs_ma: 'mid',
  rsi: 'short',
  volume_anomaly: 'short',
  relative_strength: 'mid',
  spx_ma: 'mid',
  ad_day: 'short',
  vix: 'short',
  yield_spread: 'long',
  macd: 'short',
  bollinger: 'short',
  dxy: 'long',
  fed_rate: 'long',
};
