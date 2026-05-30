import type { CalendarEvent } from '../../api/calendar';
import {
  daysSinceVerified,
  extractIndustryPayload,
} from '../../api/calendar';

interface EventChipProps {
  event: CalendarEvent;
  // True when the event's date is before today. Past events grey out
  // while still rendering — preserves the "look up what happened last
  // Friday" lookup use case.
  past: boolean;
  // Compact mode used inside day cells (lots of overlap). When false
  // the chip uses the slightly chunkier agenda-list styling.
  compact?: boolean;
  // Days since last_verified_at after which the chip is rendered
  // semi-transparent. Defaults to 21 (matches backend's
  // settings.industry_sync_stale_days default).
  staleThresholdDays?: number;
}

const TYPE_TINT: Record<
  CalendarEvent['type'],
  { bg: string; text: string; border: string }
> = {
  earnings: {
    bg: 'bg-emerald-100',
    text: 'text-emerald-800',
    border: 'border-emerald-300',
  },
  macro: {
    bg: 'bg-sky-100',
    text: 'text-sky-800',
    border: 'border-sky-300',
  },
  industry: {
    bg: 'bg-violet-100',
    text: 'text-violet-800',
    border: 'border-violet-300',
  },
};

const PAST_TINT = {
  bg: 'bg-stone-100',
  text: 'text-stone-400',
  border: 'border-stone-200',
};

// Chip displays:
//   earnings → "AAPL AMC" (ticker + optional time marker)
//   macro    → "CPI" (title condensed if needed)
//   industry → "NVDA GTC" or "SpaceX IPO" (title verbatim)
//
// Industry trust signals (only when payload carries Gemini metadata):
//   confidence=estimated → border-dashed
//   confidence=uncertain → border-dotted
//   stale (last_verified > staleThresholdDays days) → opacity-60
export function EventChip({
  event,
  past,
  compact = true,
  staleThresholdDays = 21,
}: EventChipProps): JSX.Element {
  const tint = past ? PAST_TINT : TYPE_TINT[event.type];
  const label = formatChipLabel(event);
  const padding = compact ? 'px-1.5 py-0.5' : 'px-2 py-1';
  const textSize = compact ? 'text-[10px]' : 'text-xs';
  const trust = computeTrustModifiers(event, staleThresholdDays);
  return (
    <span
      role="listitem"
      data-testid="calendar-event-chip"
      data-event-type={event.type}
      data-past={past || undefined}
      data-confidence={trust.confidence ?? undefined}
      data-stale={trust.stale || undefined}
      className={`inline-flex items-center gap-1 truncate rounded-md border ${trust.borderStyle} ${padding} ${textSize} leading-tight ${tint.bg} ${tint.text} ${tint.border} ${trust.opacity}`}
      title={trust.tooltip ?? label}
    >
      <span className="truncate">{label}</span>
    </span>
  );
}

interface TrustModifiers {
  confidence: 'confirmed' | 'estimated' | 'uncertain' | null;
  stale: boolean;
  borderStyle: string;
  opacity: string;
  tooltip: string | null;
}

function computeTrustModifiers(
  event: CalendarEvent,
  staleThresholdDays: number,
): TrustModifiers {
  if (event.type !== 'industry') {
    return {
      confidence: null,
      stale: false,
      borderStyle: 'border-solid',
      opacity: '',
      tooltip: null,
    };
  }
  const payload = extractIndustryPayload(event.payload);
  const days = daysSinceVerified(payload);
  const stale = days !== null && days >= staleThresholdDays;
  const borderStyle = (() => {
    if (payload.confidence === 'estimated') return 'border-dashed';
    if (payload.confidence === 'uncertain') return 'border-dotted';
    return 'border-solid';
  })();
  const tooltipParts: string[] = [];
  if (payload.confidence === 'estimated') {
    tooltipParts.push('依歷史模式推估');
  } else if (payload.confidence === 'uncertain') {
    tooltipParts.push('來源不一致 — 建議至官網確認');
  } else if (payload.confidence === 'confirmed') {
    tooltipParts.push('官網已確認');
  }
  if (stale && days !== null) {
    tooltipParts.push(`${days} 天未驗證`);
  }
  const tooltip = tooltipParts.length ? tooltipParts.join(' · ') : null;
  return {
    confidence: payload.confidence,
    stale,
    borderStyle,
    opacity: stale ? 'opacity-60' : '',
    tooltip,
  };
}

function formatChipLabel(event: CalendarEvent): string {
  const marker = event.eventTime ?? '';
  if (event.type === 'earnings') {
    const symbol = event.tickerSymbol ?? event.title;
    return marker ? `${symbol} ${marker}` : symbol;
  }
  // Macro / industry: title carries the meaning. Trim "Release" suffix
  // for compactness ("CPI Release" → "CPI") because the type already
  // colors the chip.
  return event.title.replace(/\s+Release$/u, '');
}
