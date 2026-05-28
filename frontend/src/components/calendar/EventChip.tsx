import type { CalendarEvent } from '../../api/calendar';

interface EventChipProps {
  event: CalendarEvent;
  // True when the event's date is before today. Past events grey out
  // while still rendering — preserves the "look up what happened last
  // Friday" lookup use case.
  past: boolean;
  // Compact mode used inside day cells (lots of overlap). When false
  // the chip uses the slightly chunkier agenda-list styling.
  compact?: boolean;
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
export function EventChip({ event, past, compact = true }: EventChipProps): JSX.Element {
  const tint = past ? PAST_TINT : TYPE_TINT[event.type];
  const label = formatChipLabel(event);
  const padding = compact ? 'px-1.5 py-0.5' : 'px-2 py-1';
  const textSize = compact ? 'text-[10px]' : 'text-xs';
  return (
    <span
      role="listitem"
      data-testid="calendar-event-chip"
      data-event-type={event.type}
      data-past={past || undefined}
      className={`inline-flex items-center gap-1 truncate rounded-md border ${padding} ${textSize} leading-tight ${tint.bg} ${tint.text} ${tint.border}`}
      title={label}
    >
      <span className="truncate">{label}</span>
    </span>
  );
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
