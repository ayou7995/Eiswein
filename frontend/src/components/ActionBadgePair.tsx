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
      className="inline-flex flex-wrap items-center gap-2"
    >
      <TimeframeLabel
        text="中期"
        ariaLabel="中期判斷 (2-4 週)"
        tone="mid"
      />
      <ActionBadge
        action={midAction}
        timingBadge={midTimingBadge}
        compact={compact}
        explainContext={{
          directionGreenCount: midGreen,
          directionRedCount: midRed,
        }}
      />
      <TimeframeLabel
        text="短期"
        ariaLabel="短期判斷 (3-5 天)"
        tone="short"
      />
      <ActionBadge
        action={shortAction}
        compact={compact}
        explainContext={{
          directionGreenCount: shortGreen,
          directionRedCount: shortRed,
        }}
      />
    </div>
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
