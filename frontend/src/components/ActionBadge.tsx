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
  explainContext,
}: ActionBadgeProps): JSX.Element {
  const preset = ACTION_PRESETS[action];
  const ariaLabel = timingBadge
    ? `${preset.ariaLabel}，時機提示：${timingBadge}`
    : preset.ariaLabel;

  const badge = (
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

  if (explainContext === undefined) return badge;

  return (
    <Explainable
      title="建議動作判定規則"
      marker="none"
      explanation={
        <RuleTable
          preface="由 4 個方向指標（Price vs MA、RSI、成交量、相對強度）的紅綠燈計票。決策表由上往下掃，高信心動作優先（如 2🟢/1🔴 → 持有，不會降為觀望）。黃燈不算票。"
          rows={buildActionRuleRows(action, explainContext.directionGreenCount, explainContext.directionRedCount)}
          currentValueText={`你目前: 綠燈 ${explainContext.directionGreenCount} · 紅燈 ${explainContext.directionRedCount} → ${preset.emoji} ${preset.label}`}
          note="時機指標（MACD / Bollinger）不影響 action，只在買進方向加上「✓ 時機好」或「⏳ 等回調」修飾。"
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
