export type PriceBarTone = 'green' | 'red' | 'neutral';

export interface PriceBarProps {
  currentPrice: number | null;
  targetPrice: number | null;
  label: string;
  // Colour used when currentPrice > targetPrice (default neutral).
  toneAboveTarget?: PriceBarTone;
  // Colour used when currentPrice <= targetPrice (default neutral).
  toneBelowTarget?: PriceBarTone;
  // Optional copy describing what "above target" means for screen readers
  // (e.g. "高於停損"). Falls back to a generic description.
  ariaLabel?: string;
}

const TONE_BAR: Record<PriceBarTone, string> = {
  green: 'bg-signal-green',
  red: 'bg-signal-red',
  neutral: 'bg-slate-400',
};

const TONE_TEXT: Record<PriceBarTone, string> = {
  green: 'text-signal-green',
  red: 'text-signal-red',
  neutral: 'text-slate-300',
};

function formatPrice(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return '—';
  return value.toFixed(2);
}

// Percentage position of `current` inside a fixed ±25% window around the
// target. Kept deliberately simple: the bar is a *relative* hint, not a
// precise chart. Clamped to [0, 100] so the marker never leaves the track.
function markerPosition(current: number, target: number): number {
  if (target === 0) return 50;
  const deltaPct = ((current - target) / target) * 100;
  const clamped = Math.max(-25, Math.min(25, deltaPct));
  return ((clamped + 25) / 50) * 100;
}

export function PriceBar({
  currentPrice,
  targetPrice,
  label,
  toneAboveTarget = 'neutral',
  toneBelowTarget = 'neutral',
  ariaLabel,
}: PriceBarProps): JSX.Element {
  const hasBoth = currentPrice !== null && targetPrice !== null;
  const isAbove = hasBoth && (currentPrice as number) > (targetPrice as number);
  const tone: PriceBarTone = !hasBoth
    ? 'neutral'
    : isAbove
      ? toneAboveTarget
      : toneBelowTarget;
  const resolvedAria =
    ariaLabel ??
    (hasBoth
      ? `${label}：目前 ${formatPrice(currentPrice)}，目標 ${formatPrice(targetPrice)}`
      : `${label}：資料不足`);
  const position = hasBoth
    ? markerPosition(currentPrice as number, targetPrice as number)
    : 50;

  return (
    <div
      role="group"
      aria-label={resolvedAria}
      data-testid="price-bar"
      className="flex flex-col gap-1"
    >
      <div className="flex items-baseline justify-between text-xs text-slate-400">
        <span className="font-medium text-slate-300">{label}</span>
        <span className={`font-mono ${TONE_TEXT[tone]}`}>
          {formatPrice(currentPrice)}
          <span aria-hidden="true" className="mx-1 text-slate-600">
            vs
          </span>
          <span className="text-slate-400">{formatPrice(targetPrice)}</span>
        </span>
      </div>
      <div className="relative h-2 w-full overflow-hidden rounded-full bg-slate-800">
        <div
          aria-hidden="true"
          data-testid="price-bar-target"
          className="absolute top-0 bottom-0 left-1/2 w-px bg-slate-500"
        />
        {hasBoth && (
          <div
            aria-hidden="true"
            data-testid="price-bar-marker"
            className={`absolute top-0 bottom-0 h-2 w-2 rounded-full shadow ${TONE_BAR[tone]}`}
            style={{ left: `calc(${position.toFixed(2)}% - 4px)` }}
          />
        )}
      </div>
    </div>
  );
}
