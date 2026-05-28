import type { CalendarEvent } from '../../api/calendar';
import { EventChip } from './EventChip';

interface DayCellProps {
  date: Date;
  events: readonly CalendarEvent[];
  inCurrentMonth: boolean;
  isToday: boolean;
  isPast: boolean;
  onOpen: (date: Date) => void;
}

// Cap on inline chips. Anything beyond this folds into a "+N" affordance
// that opens the day drawer. Three chips per cell is the legibility
// sweet-spot at 7-col grid widths on a 1440px laptop.
const MAX_INLINE_CHIPS = 3;

export function DayCell({
  date,
  events,
  inCurrentMonth,
  isToday,
  isPast,
  onOpen,
}: DayCellProps): JSX.Element {
  const dayNum = date.getDate();
  const visible = events.slice(0, MAX_INLINE_CHIPS);
  const overflow = events.length - visible.length;

  const bg = isToday
    ? 'bg-amber-50'
    : inCurrentMonth
      ? 'bg-white'
      : 'bg-stone-50';
  const dimText = !inCurrentMonth || isPast;

  const handleClick = (): void => onOpen(date);
  const handleKey = (event: React.KeyboardEvent<HTMLDivElement>): void => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      onOpen(date);
    }
  };

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={handleClick}
      onKeyDown={handleKey}
      data-testid={`calendar-day-${date.getFullYear()}-${date.getMonth() + 1}-${date.getDate()}`}
      data-today={isToday || undefined}
      aria-label={ariaLabelFor(date, events)}
      className={`flex min-h-[88px] flex-col gap-1 border border-stone-200 p-1 text-left transition hover:bg-stone-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500 ${bg}`}
    >
      <div className="flex items-center justify-between">
        <span
          className={`text-xs font-semibold ${
            isToday
              ? 'text-amber-700'
              : dimText
                ? 'text-stone-400'
                : 'text-stone-700'
          }`}
        >
          {dayNum}
        </span>
        {isToday && (
          <span
            aria-hidden="true"
            className="rounded-full bg-amber-200 px-1 py-px text-[9px] font-semibold uppercase tracking-wide text-amber-800"
          >
            今日
          </span>
        )}
      </div>
      {events.length === 0 ? (
        // Empty cell — keep cell tall so the row doesn't collapse.
        <div aria-hidden="true" className="flex-1" />
      ) : (
        <div
          role="list"
          aria-label={`${date.getMonth() + 1}/${date.getDate()} 事件`}
          className="flex flex-col gap-0.5 overflow-hidden"
        >
          {visible.map((evt) => (
            <EventChip key={evt.id} event={evt} past={isPast} compact />
          ))}
          {overflow > 0 && (
            <span
              data-testid="calendar-day-overflow"
              className="rounded-md bg-stone-100 px-1 py-px text-[10px] text-stone-600"
            >
              +{overflow} 還有…
            </span>
          )}
        </div>
      )}
    </div>
  );
}

function ariaLabelFor(date: Date, events: readonly CalendarEvent[]): string {
  const base = `${date.getFullYear()} 年 ${date.getMonth() + 1} 月 ${date.getDate()} 日`;
  if (events.length === 0) return base;
  if (events.length === 1) {
    const first = events[0];
    return first ? `${base},${first.title}` : base;
  }
  return `${base},共 ${events.length} 件事件`;
}
