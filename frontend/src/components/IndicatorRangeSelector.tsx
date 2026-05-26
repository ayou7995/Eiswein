import {
  MARKET_INDICATOR_RANGES,
  type MarketIndicatorRangeKey,
} from '../api/marketIndicatorSeries';

export interface IndicatorRangeSelectorProps {
  value: MarketIndicatorRangeKey;
  onChange: (range: MarketIndicatorRangeKey) => void;
  // Indicator name only used in the aria-label for context.
  indicatorLabel?: string;
}

// Compact 5-button range selector (1M / 3M / 6M / 1Y / 2Y) that
// callers wire above each market-indicator chart. Same pattern as the
// CandlestickChart's PriceRange selector but generalized to the
// market-indicator name space.
export function IndicatorRangeSelector({
  value,
  onChange,
  indicatorLabel,
}: IndicatorRangeSelectorProps): JSX.Element {
  return (
    <div
      role="radiogroup"
      aria-label={indicatorLabel ? `${indicatorLabel} 區間` : '指標區間'}
      className="inline-flex rounded-md border border-stone-300 bg-stone-50 p-0.5"
    >
      {MARKET_INDICATOR_RANGES.map((option) => {
        const active = option.key === value;
        return (
          <button
            key={option.key}
            type="button"
            role="radio"
            aria-checked={active}
            data-testid={`indicator-range-${option.key}`}
            onClick={() => onChange(option.key)}
            className={`rounded px-2 py-0.5 text-[11px] font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400 ${
              active
                ? 'bg-sky-600 text-white'
                : 'text-stone-700 hover:bg-stone-100 hover:text-stone-900'
            }`}
          >
            {option.key}
          </button>
        );
      })}
    </div>
  );
}
