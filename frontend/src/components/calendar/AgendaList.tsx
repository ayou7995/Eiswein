import type { CalendarEvent } from '../../api/calendar';
import { EventChip } from './EventChip';

interface AgendaListProps {
  events: readonly CalendarEvent[];
  today: Date;
  onDayClick: (date: Date) => void;
}

// Mobile-friendly time-sorted list grouped by date. Renders the same
// upstream events that the MonthGrid uses — single source of truth on
// the parent's hook. Tapping a date header opens the day drawer for
// parity with the desktop grid's cell tap.
export function AgendaList({ events, today, onDayClick }: AgendaListProps): JSX.Element {
  const byDate = new Map<string, CalendarEvent[]>();
  for (const evt of events) {
    const key = isoKey(evt.eventDate);
    const bucket = byDate.get(key);
    if (bucket) {
      bucket.push(evt);
    } else {
      byDate.set(key, [evt]);
    }
  }
  const orderedKeys = Array.from(byDate.keys()).sort();
  if (orderedKeys.length === 0) {
    return (
      <div className="rounded-lg border border-stone-200 bg-white p-8 text-center text-sm text-stone-500">
        本區間沒有任何事件
      </div>
    );
  }

  const todayKey = isoKey(today);

  return (
    <ul
      role="list"
      aria-label="事件清單"
      data-testid="calendar-agenda-list"
      className="flex flex-col gap-3"
    >
      {orderedKeys.map((dateKey) => {
        const dayEvents = byDate.get(dateKey) ?? [];
        const date = parseIsoDate(dateKey);
        const isPast = dateKey < todayKey;
        return (
          <li
            key={dateKey}
            className="overflow-hidden rounded-lg border border-stone-200 bg-white"
          >
            <button
              type="button"
              onClick={() => onDayClick(date)}
              className={`flex w-full items-baseline justify-between gap-2 px-3 py-2 text-left ${
                dateKey === todayKey
                  ? 'bg-amber-50 text-amber-800'
                  : 'bg-stone-50 text-stone-700 hover:bg-stone-100'
              }`}
            >
              <span className="text-sm font-semibold">
                {date.getMonth() + 1}/{date.getDate()}{' '}
                <span className="ml-1 text-xs text-stone-500">
                  {WEEKDAY_LABELS[date.getDay()]}
                </span>
              </span>
              <span className="text-xs text-stone-500">{dayEvents.length} 件</span>
            </button>
            <ul role="list" className="flex flex-col gap-1 px-3 py-2">
              {dayEvents.map((evt) => (
                <li key={evt.id} className="flex items-center gap-2">
                  <EventChip event={evt} past={isPast} compact={false} />
                  {evt.tickerSymbol && evt.type !== 'earnings' && (
                    <span className="text-xs text-stone-500">{evt.tickerSymbol}</span>
                  )}
                  <span className="ml-auto text-xs text-stone-400">
                    {evt.title}
                  </span>
                </li>
              ))}
            </ul>
          </li>
        );
      })}
    </ul>
  );
}

const WEEKDAY_LABELS: readonly string[] = ['週日', '週一', '週二', '週三', '週四', '週五', '週六'];

function isoKey(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

function parseIsoDate(iso: string): Date {
  const [yStr, mStr, dStr] = iso.split('-');
  return new Date(
    Number.parseInt(yStr ?? '', 10),
    Number.parseInt(mStr ?? '', 10) - 1,
    Number.parseInt(dStr ?? '', 10),
  );
}
