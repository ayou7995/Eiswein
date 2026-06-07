import type { ActionCategoryCode } from '../api/tickerSignal';
import { Explainable, RuleTable, type RuleTableRow } from './Explainable';

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
    classes: 'bg-stone-100 text-stone-800 border-stone-300',
    ariaLabel: '建議動作：持有',
  },
  watch: {
    emoji: '👀',
    letter: 'W',
    label: '觀望',
    classes: 'bg-stone-100 text-stone-700 border-stone-300',
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

// Compact preset — used in the sidebar grouped watchlist where row height
// matters more than redundancy. Single emoji + shortened 2-char label, no
// letter. STRONG_BUY uses ⏫ (semantically "more up than 🟢") so it stays
// distinguishable from BUY at a glance even after the visual weight is
// flattened. Color-blind redundancy: the bg saturation gradient (200 → 50
// → 100 → stone) plus position in the rule table still differentiates
// conviction levels.
const ACTION_COMPACT_PRESETS: Record<
  ActionCategoryCode,
  { emoji: string; label: string; classes: string }
> = {
  strong_buy: {
    emoji: '⏫',
    label: '強買',
    classes: 'bg-emerald-200 text-emerald-800 font-semibold',
  },
  buy: {
    emoji: '🟢',
    label: '買入',
    classes: 'bg-emerald-100 text-emerald-700',
  },
  hold: {
    emoji: '✓',
    label: '持有',
    classes: 'bg-stone-100 text-stone-700',
  },
  watch: {
    emoji: '👀',
    label: '觀望',
    classes: 'bg-stone-100 text-stone-500',
  },
  reduce: {
    emoji: '⚠',
    label: '減倉',
    classes: 'bg-amber-100 text-amber-700',
  },
  exit: {
    emoji: '🔴',
    label: '出場',
    classes: 'bg-rose-200 text-rose-800 font-semibold',
  },
};

export interface ActionBadgeProps {
  action: ActionCategoryCode;
  // Optional timing badge suffix (e.g. "✓ 時機好" / "⏳ 等回調"). Backend emits
  // null when suppressed (per show_timing_modifier rule); we never fabricate.
  timingBadge?: string | null;
  className?: string;
  // When true, renders the slim sidebar variant: single emoji + 2-char label,
  // no letter, no border, smaller padding. Same aria-label as default for a11y.
  compact?: boolean;
  // When provided, wraps the badge in an Explainable popover that surfaces
  // the 6-row direction decision table with the user's current
  // green/red vote counts highlighted. Without this prop the badge
  // renders bare (used in tests / places where the action is already
  // explained nearby).
  explainContext?: {
    directionGreenCount: number;
    directionRedCount: number;
  };
}

export function ActionBadge({
  action,
  timingBadge = null,
  className = '',
  compact = false,
  explainContext,
}: ActionBadgeProps): JSX.Element {
  const preset = ACTION_PRESETS[action];
  const ariaLabel = timingBadge
    ? `${preset.ariaLabel}，時機提示：${timingBadge}`
    : preset.ariaLabel;

  const badge = compact ? (() => {
    const c = ACTION_COMPACT_PRESETS[action];
    return (
      <span
        role="status"
        aria-label={ariaLabel}
        data-testid="action-badge"
        data-action={action}
        data-compact="true"
        className={`inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs leading-none ${c.classes} ${className}`}
      >
        <span aria-hidden="true" className="text-[11px]">{c.emoji}</span>
        <span aria-hidden="true">{c.label}</span>
        {timingBadge && (
          <span
            aria-hidden="true"
            data-testid="action-badge-timing"
            className="ml-0.5 rounded-full bg-white/60 px-1 py-px text-[9px] font-medium text-stone-700"
          >
            {timingBadge}
          </span>
        )}
      </span>
    );
  })() : (
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
          className="ml-1 rounded-full border border-stone-300 bg-white px-1.5 py-0.5 text-[10px] font-medium text-stone-700"
        >
          {timingBadge}
        </span>
      )}
    </span>
  );

  if (explainContext === undefined) return badge;

  return (
    <Explainable
      title="建議動作判定規則"
      marker="none"
      explanation={
        <RuleTable
          preface="由 5 個方向指標的紅黃綠燈計票決定 action。中期 (2-4 週) 用 price_vs_ma + rsi + volume_anomaly + relative_strength + cho;短期 (3-5 天) 用 rsi + macd + bollinger + volume_anomaly + ttm_squeeze。決策表由上往下掃,高信心動作優先 (如 3🟢/1🔴 → 持有,不會降為觀望)。黃燈不算票。"
          rows={buildActionRuleRows(action, explainContext.directionGreenCount, explainContext.directionRedCount)}
          currentValueText={`你目前: 綠燈 ${explainContext.directionGreenCount} · 紅燈 ${explainContext.directionRedCount} → ${preset.emoji} ${preset.label}`}
          note="時機指標 (MACD / Bollinger) 跟 ADX / ATR 不影響 mid action,只在買進方向加上「✓ 時機好」或「⏳ 等回調」修飾。"
        />
      }
    >
      {badge}
    </Explainable>
  );
}

// Decision-table rows mirroring `backend/app/signals/direction.py:_DIRECTION_TABLE`.
// Source of truth lives in Python; this is the human-readable presentation
// of the same rule. Any change to the table must update both sides.
function buildActionRuleRows(
  current: ActionCategoryCode,
  green: number,
  red: number,
): RuleTableRow[] {
  const matches = (a: ActionCategoryCode, g: [number, number], r: [number, number]): boolean =>
    a === current && green >= g[0] && green <= g[1] && red >= r[0] && red <= r[1];
  return [
    {
      condition: '綠 4 / 紅 0',
      result: '🟢🟢 強力買入',
      current: matches('strong_buy', [4, 4], [0, 0]),
    },
    {
      condition: '綠 3 / 紅 0-1',
      result: '🟢 買入',
      current: matches('buy', [3, 3], [0, 1]),
    },
    {
      condition: '綠 2 / 紅 0-1',
      result: '✓ 持有',
      current: matches('hold', [2, 2], [0, 1]),
    },
    {
      condition: '綠 1-2 / 紅 1-2',
      result: '👀 觀望',
      current: matches('watch', [1, 2], [1, 2]) || (current === 'watch' && green === 0 && red === 0),
    },
    {
      condition: '綠 0-1 / 紅 2-3',
      result: '⚠️ 減倉',
      current: matches('reduce', [0, 1], [2, 3]),
    },
    {
      condition: '綠 0 / 紅 4',
      result: '🔴🔴 出場',
      current: matches('exit', [0, 0], [4, 4]),
    },
  ];
}
