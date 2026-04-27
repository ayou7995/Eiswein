// Generic trend display: shows direction over a window with magnitude and
// an indicator-specific interpretation phrase. Reusable across VIX (10-day
// fear trend), DXY (20-day dollar trend), Fed (30-day rate delta), etc.

export type TrendDirection = 'rising' | 'falling' | 'flat' | 'unknown';

export interface TrendPillProps {
  direction: TrendDirection;
  // Signed delta value for the window (e.g. -2.12 for VIX 10-day change).
  // Pass `null` when not computable (insufficient history); the pill
  // still renders but shows "—" instead of a number.
  magnitude: number | null;
  windowLabel: string;
  // Per-direction interpretation text (e.g. for VIX "rising" → "恐慌升溫，
  // 對股市偏弱"). Each direction can render its own short clause.
  interpretations: Record<TrendDirection, string>;
  // Tone mapping per direction. Defaults to a "rising-is-bad" palette
  // (rising → red, falling → green) which fits VIX/DXY semantics; callers
  // with inverted semantics can override.
  toneOverride?: Partial<Record<TrendDirection, 'pro' | 'con' | 'neutral'>>;
}

const DEFAULT_TONE: Record<TrendDirection, 'pro' | 'con' | 'neutral'> = {
  rising: 'con',
  falling: 'pro',
  flat: 'neutral',
  unknown: 'neutral',
};

const DIRECTION_EMOJI: Record<TrendDirection, string> = {
  rising: '📈',
  falling: '📉',
  flat: '📊',
  unknown: '⚪',
};

const TONE_CLASS: Record<'pro' | 'con' | 'neutral', string> = {
  pro: 'border-signal-green/40 bg-signal-green/10 text-signal-green',
  con: 'border-signal-red/40 bg-signal-red/10 text-signal-red',
  neutral: 'border-slate-700 bg-slate-950/40 text-slate-300',
};

function formatMagnitude(value: number | null): string {
  if (value === null) return '—';
  const sign = value > 0 ? '+' : '';
  return `${sign}${value.toFixed(2)}`;
}

export function TrendPill({
  direction,
  magnitude,
  windowLabel,
  interpretations,
  toneOverride,
}: TrendPillProps): JSX.Element {
  const tone = toneOverride?.[direction] ?? DEFAULT_TONE[direction];
  const interp = interpretations[direction];
  return (
    <div
      role="status"
      aria-label={`${windowLabel}趨勢：${interp}`}
      className={`flex flex-wrap items-center gap-2 rounded-md border px-3 py-2 text-xs ${TONE_CLASS[tone]}`}
    >
      <span aria-hidden="true">{DIRECTION_EMOJI[direction]}</span>
      <span className="text-slate-300">{windowLabel}</span>
      <span className="font-mono tabular-nums">{formatMagnitude(magnitude)}</span>
      <span className="text-slate-500">·</span>
      <span>{interp}</span>
    </div>
  );
}
