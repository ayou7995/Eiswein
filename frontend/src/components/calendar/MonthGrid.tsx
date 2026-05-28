import { DayCell } from './DayCell';
import type { CalendarEvent } from '../../api/calendar';

interface MonthGridProps {
  // First-of-month anchor; the grid pads back to the prior Sunday and
  // forward to fill 6 weeks (42 cells). Adjacent-month dates render in
  // muted text so the operator still sees "Mon Sep 1" if Aug ends mid-week.
  monthAnchor: Date;
  today: Date;
  // Pre-bucketed events by ISO date so the grid doesn't re-filter on
  // every cell render.
  eventsByDate: ReadonlyMap<string, readonly CalendarEvent[]>;
  onDayClick: (date: Date) => void;
}

const WEEKDAYS_ZH: readonly string[] = ['日', '一', '二', '三', '四', '五', '六'];

function isoKey(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function sameDay(a: Date, b: Date): boolean {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  );
}

function startOfWeek(date: Date): Date {
  const out = new Date(date);
  out.setDate(out.getDate() - out.getDay());
  out.setHours(0, 0, 0, 0);
  return out;
}

export function MonthGrid({
  monthAnchor,
  today,
  eventsByDate,
  onDayClick,
}: MonthGridProps): JSX.Element {
  const monthStart = new Date(monthAnchor.getFullYear(), monthAnchor.getMonth(), 1);
  const gridStart = startOfWeek(monthStart);
  const cells: Date[] = [];
  for (let i = 0; i < 42; i += 1) {
    const d = new Date(gridStart);
    d.setDate(gridStart.getDate() + i);
    cells.push(d);
  }
  return (
    <div
      role="grid"
      aria-label={`${monthStart.getFullYear()} 年 ${monthStart.getMonth() + 1} 月 行事曆`}
      data-testid="calendar-month-grid"
      className="overflow-hidden rounded-lg border border-stone-200 bg-white"
    >
      <div role="row" className="grid grid-cols-7 border-b border-stone-200 bg-stone-50">
        {WEEKDAYS_ZH.map((day, idx) => (
          <div
            key={day}
            role="columnheader"
            className={`px-2 py-1.5 text-center text-xs font-semibold uppercase tracking-wide ${
              idx === 0 || idx === 6 ? 'text-rose-500' : 'text-stone-500'
            }`}
          >
            {day}
          </div>
        ))}
      </div>
      <div role="rowgroup" className="grid grid-cols-7">
        {cells.map((cell) => {
          const inCurrentMonth = cell.getMonth() === monthStart.getMonth();
          const isToday = sameDay(cell, today);
          const isPast = cell.getTime() < new Date(today.getFullYear(), today.getMonth(), today.getDate()).getTime();
          const dayEvents = eventsByDate.get(isoKey(cell)) ?? [];
          return (
            <DayCell
              key={cell.toISOString()}
              date={cell}
              events={dayEvents}
              inCurrentMonth={inCurrentMonth}
              isToday={isToday}
              isPast={isPast}
              onOpen={onDayClick}
            />
          );
        })}
      </div>
    </div>
  );
}
