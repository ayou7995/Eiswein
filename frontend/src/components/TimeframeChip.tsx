import {
  INDICATOR_TIMEFRAMES,
  TIMEFRAME_STYLE,
  type Timeframe,
} from '../lib/timeframes';

export interface TimeframeChipProps {
  // Either pass the resolved timeframe (preferred — backend supplies it
  // on every ProsConsItem) or an indicatorName so callers without a
  // ProsConsItem in hand can still render the chip via the local map.
  timeframe?: Timeframe;
  indicatorName?: string;
}

// Small rounded chip showing 短期 / 中期 / 長期 with role=status semantics
// so screen readers announce the horizon. Returns null silently when the
// indicator name isn't recognised — keeps the surrounding UI clean even
// if a future indicator lands before its timeframe mapping is updated.
export function TimeframeChip({
  timeframe,
  indicatorName,
}: TimeframeChipProps): JSX.Element | null {
  const resolved =
    timeframe ?? (indicatorName ? INDICATOR_TIMEFRAMES[indicatorName] : undefined);
  if (!resolved) return null;
  const tf = TIMEFRAME_STYLE[resolved];
  return (
    <span
      role="status"
      data-testid="timeframe-chip"
      aria-label={tf.ariaLabel}
      className={`inline-flex items-center rounded-full border px-1.5 py-0.5 text-[10px] font-medium leading-none ${tf.className}`}
    >
      {tf.label}
    </span>
  );
}
