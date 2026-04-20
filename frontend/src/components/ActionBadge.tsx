import type { ActionCategoryCode } from '../api/tickerSignal';

// ActionBadge — I1 direction layer. Triple redundancy (emoji + Chinese label
// + letter) per STAFF_REVIEW_DECISIONS.md I20 for color-blind users. Distinct
// visual weights (bg / border) separate high-conviction actions (STRONG_BUY,
// EXIT) from middle-conviction (BUY, REDUCE) and default (HOLD, WATCH).
const ACTION_PRESETS: Record<
  ActionCategoryCode,
  { emoji: string; letter: string; label: string; classes: string; ariaLabel: string }
> = {
  strong_buy: {
    emoji: '🟢🟢',
    letter: 'S',
    label: '強力買入',
    classes:
      'bg-signal-green/25 text-signal-green border-signal-green font-bold',
    ariaLabel: '建議動作：強力買入',
  },
  buy: {
    emoji: '🟢',
    letter: 'B',
    label: '買入',
    classes: 'bg-signal-green/15 text-signal-green border-signal-green/40',
    ariaLabel: '建議動作：買入',
  },
  hold: {
    emoji: '✓',
    letter: 'H',
    label: '持有',
    classes: 'bg-slate-500/10 text-slate-200 border-slate-500/40',
    ariaLabel: '建議動作：持有',
  },
  watch: {
    emoji: '👀',
    letter: 'W',
    label: '觀望',
    classes: 'bg-slate-500/10 text-slate-300 border-slate-500/40',
    ariaLabel: '建議動作：觀望',
  },
  reduce: {
    emoji: '⚠️',
    letter: 'D',
    label: '減倉',
    classes: 'bg-signal-yellow/15 text-signal-yellow border-signal-yellow/40',
    ariaLabel: '建議動作：減倉',
  },
  exit: {
    emoji: '🔴🔴',
    letter: 'E',
    label: '出場',
    classes: 'bg-signal-red/25 text-signal-red border-signal-red font-bold',
    ariaLabel: '建議動作：出場',
  },
};

export interface ActionBadgeProps {
  action: ActionCategoryCode;
  // Optional timing badge suffix (e.g. "✓ 時機好" / "⏳ 等回調"). Backend emits
  // null when suppressed (per show_timing_modifier rule); we never fabricate.
  timingBadge?: string | null;
  className?: string;
}

export function ActionBadge({
  action,
  timingBadge = null,
  className = '',
}: ActionBadgeProps): JSX.Element {
  const preset = ACTION_PRESETS[action];
  const ariaLabel = timingBadge
    ? `${preset.ariaLabel}，時機提示：${timingBadge}`
    : preset.ariaLabel;
  return (
    <span
      role="status"
      aria-label={ariaLabel}
      data-testid="action-badge"
      data-action={action}
      className={`inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-sm ${preset.classes} ${className}`}
    >
      <span aria-hidden="true">{preset.emoji}</span>
      <span aria-hidden="true">{preset.label}</span>
      <span aria-hidden="true" className="text-xs font-bold opacity-70">
        {preset.letter}
      </span>
      {timingBadge && (
        <span
          aria-hidden="true"
          data-testid="action-badge-timing"
          className="ml-1 rounded-full border border-slate-600 bg-slate-900/60 px-1.5 py-0.5 text-[10px] font-medium text-slate-300"
        >
          {timingBadge}
        </span>
      )}
    </span>
  );
}
