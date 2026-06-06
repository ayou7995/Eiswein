import type { ActionCategoryCode } from '../api/tickerSignal';
import { ActionBadge } from './ActionBadge';

// Renders the mid-term + short-term ActionBadge side by side. v2 Phase 1
// (2026-06) split the single dashboard verdict into two horizons; this
// component is the visual home for that split. Each side carries its own
// timeframe label so the operator can read "中期: 持有 / 短期: 🟢 買入"
// at a glance even when the two votes disagree (which is the feature —
// short-term tactical entries on days when the mid-term picture is fine).
//
// Both badges accept their own ``explainContext`` so the popover surfaces
// the vote counts that actually drove that side's verdict (the mid badge
// shows the 4 direction indicators' counts; the short badge shows the
// short-horizon vote counts).

export interface ActionBadgePairProps {
  midAction: ActionCategoryCode;
  midGreen: number;
  midRed: number;
  midTimingBadge?: string | null;
  shortAction: ActionCategoryCode;
  shortGreen: number;
  shortRed: number;
  // Compact variant flattens both badges to the sidebar slim form. Used
  // in watchlist rows where the row height matters more than redundancy.
  compact?: boolean;
}

// v2 Phase 1+3 vote totals — both ladders now run 5 indicators each
// after CHO (mid) and TTM Squeeze (short) joined the tables. Used by the
// vote-tally subtitle so the operator can see at a glance how unanimous
// the verdict is without opening the popover.
const MID_VOTE_TOTAL = 5;
const SHORT_VOTE_TOTAL = 5;

export function ActionBadgePair({
  midAction,
  midGreen,
  midRed,
  midTimingBadge = null,
  shortAction,
  shortGreen,
  shortRed,
  compact = false,
}: ActionBadgePairProps): JSX.Element {
  return (
    <div
      data-testid="action-badge-pair"
      className="inline-flex flex-wrap items-start gap-3"
    >
      <BadgeColumn
        label="中期"
        labelAria="中期判斷 (2-4 週)"
        labelTone="mid"
        action={midAction}
        timingBadge={midTimingBadge}
        compact={compact}
        green={midGreen}
        red={midRed}
        total={MID_VOTE_TOTAL}
      />
      <BadgeColumn
        label="短期"
        labelAria="短期判斷 (3-5 天)"
        labelTone="short"
        action={shortAction}
        compact={compact}
        green={shortGreen}
        red={shortRed}
        total={SHORT_VOTE_TOTAL}
      />
    </div>
  );
}

interface BadgeColumnProps {
  label: string;
  labelAria: string;
  labelTone: 'short' | 'mid' | 'long';
  action: ActionCategoryCode;
  timingBadge?: string | null;
  compact: boolean;
  green: number;
  red: number;
  total: number;
}

function BadgeColumn({
  label,
  labelAria,
  labelTone,
  action,
  timingBadge = null,
  compact,
  green,
  red,
  total,
}: BadgeColumnProps): JSX.Element {
  return (
    <div className="flex flex-col items-start gap-1">
      <div className="inline-flex items-center gap-2">
        <TimeframeLabel text={label} ariaLabel={labelAria} tone={labelTone} />
        <ActionBadge
          action={action}
          timingBadge={timingBadge}
          compact={compact}
          explainContext={{
            directionGreenCount: green,
            directionRedCount: red,
          }}
        />
      </div>
      <VoteTally green={green} red={red} total={total} />
    </div>
  );
}

interface VoteTallyProps {
  green: number;
  red: number;
  total: number;
}

function VoteTally({ green, red, total }: VoteTallyProps): JSX.Element {
  const neutral = Math.max(0, total - green - red);
  return (
    <span
      aria-label={`投票分布:${green} 綠、${red} 紅、${neutral} 中性`}
      data-testid="action-vote-tally"
      className="pl-1 font-mono text-[11px] text-stone-500"
    >
      <span className="text-signal-green">{green}🟢</span>
      <span className="mx-1 text-stone-300">·</span>
      <span className="text-signal-red">{red}🔴</span>
      <span className="mx-1 text-stone-300">·</span>
      <span>{neutral}⚪</span>
    </span>
  );
}

interface TimeframeLabelProps {
  text: string;
  ariaLabel: string;
  tone: 'short' | 'mid' | 'long';
}

function TimeframeLabel({ text, ariaLabel, tone }: TimeframeLabelProps): JSX.Element {
  const toneClasses: Record<TimeframeLabelProps['tone'], string> = {
    short: 'bg-sky-50 text-sky-700 border-sky-200',
    mid: 'bg-violet-50 text-violet-700 border-violet-200',
    long: 'bg-teal-50 text-teal-700 border-teal-200',
  };
  return (
    <span
      aria-label={ariaLabel}
      data-tone={tone}
      data-testid={`action-badge-pair-label-${tone}`}
      className={`inline-flex items-center rounded-md border px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide ${toneClasses[tone]}`}
    >
      {text}
    </span>
  );
}
