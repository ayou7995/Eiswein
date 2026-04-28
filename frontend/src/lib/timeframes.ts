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
