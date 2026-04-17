export type SignalTone = 'green' | 'yellow' | 'red';

// Text + shape redundancy for color-blind users (STAFF_REVIEW_DECISIONS.md I20).
// Each tone renders as emoji + single Chinese character + letter indicator,
// so the badge is readable even with no colour perception at all.
const TONE_PRESET: Record<
  SignalTone,
  { emoji: string; letter: string; label: string; classes: string }
> = {
  green: {
    emoji: '🟢',
    letter: 'G',
    label: '買',
    classes: 'bg-signal-green/15 text-signal-green border-signal-green/40',
  },
  yellow: {
    emoji: '🟡',
    letter: 'Y',
    label: '持',
    classes: 'bg-signal-yellow/15 text-signal-yellow border-signal-yellow/40',
  },
  red: {
    emoji: '🔴',
    letter: 'R',
    label: '賣',
    classes: 'bg-signal-red/15 text-signal-red border-signal-red/40',
  },
};

export interface SignalBadgeProps {
  tone: SignalTone;
  // Verbose text surfaced to screen readers so context stays clear when a badge
  // sits next to a ticker symbol or indicator row.
  ariaLabel: string;
  className?: string;
}

export function SignalBadge({ tone, ariaLabel, className = '' }: SignalBadgeProps): JSX.Element {
  const preset = TONE_PRESET[tone];
  return (
    <span
      role="status"
      aria-label={ariaLabel}
      data-testid="signal-badge"
      data-tone={tone}
      className={`inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-sm font-medium ${preset.classes} ${className}`}
    >
      <span aria-hidden="true">{preset.emoji}</span>
      <span aria-hidden="true">{preset.label}</span>
      <span aria-hidden="true" className="text-xs font-bold opacity-70">
        {preset.letter}
      </span>
    </span>
  );
}
