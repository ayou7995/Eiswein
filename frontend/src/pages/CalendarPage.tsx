import { useMemo, useState, type ReactNode } from 'react';
import { useSearchParams } from 'react-router-dom';
import { LoadingSpinner } from '../components/LoadingSpinner';
import { MonthGrid } from '../components/calendar/MonthGrid';
import { AgendaList } from '../components/calendar/AgendaList';
import { EventDrawer } from '../components/calendar/EventDrawer';
import { EventTypeFilter } from '../components/calendar/EventTypeFilter';
import type { CalendarEvent, EventType } from '../api/calendar';
import { useCalendarEvents } from '../hooks/useCalendar';

// 行事曆 page — catalyst calendar v1 entry point.
//
// Default view is the monthly grid; on screens below `lg` (1024px) it
// flips to an agenda list. The same data feeds both — `useCalendarEvents`
// returns the full month's events from the backend, and the rendering
// layer picks how to display.
//
// Past dates remain visible (grey-out) so the operator can answer
// "when was last CPI?" without scrolling backwards through history.
//
// `?date=YYYY-MM-DD` query param (set by NextCatalystChip and the
// MarketOverview banner) navigates the view to that month and opens
// the day drawer immediately.

const PAST_LOOKBACK_DAYS = 30;
const FUTURE_HORIZON_DAYS = 90;

function startOfMonth(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), 1);
}

function addMonths(date: Date, offset: number): Date {
  return new Date(date.getFullYear(), date.getMonth() + offset, 1);
}

function addDays(date: Date, offset: number): Date {
  const out = new Date(date);
  out.setDate(out.getDate() + offset);
  return out;
}

function isoKey(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

function startOfDay(date: Date): Date {
  const out = new Date(date);
  out.setHours(0, 0, 0, 0);
  return out;
}

export function CalendarPage(): JSX.Element {
  const [searchParams, setSearchParams] = useSearchParams();
  const today = useMemo(() => startOfDay(new Date()), []);

  // Initial anchor: either ?date=… month or today's month.
  const initialAnchor = useMemo<Date>(() => {
    const param = searchParams.get('date');
    if (!param) return startOfMonth(today);
    const parts = param.split('-');
    const parsedYear = Number.parseInt(parts[0] ?? '', 10);
    const parsedMonth = Number.parseInt(parts[1] ?? '', 10);
    if (Number.isFinite(parsedYear) && Number.isFinite(parsedMonth)) {
      return new Date(parsedYear, parsedMonth - 1, 1);
    }
    return startOfMonth(today);
  }, [searchParams, today]);

  const [monthAnchor, setMonthAnchor] = useState<Date>(initialAnchor);
  const [selectedTypes, setSelectedTypes] = useState<ReadonlySet<EventType>>(new Set());
  const [openDate, setOpenDate] = useState<Date | null>(() => {
    const param = searchParams.get('date');
    if (!param) return null;
    const parts = param.split('-');
    const py = Number.parseInt(parts[0] ?? '', 10);
    const pm = Number.parseInt(parts[1] ?? '', 10);
    const pd = Number.parseInt(parts[2] ?? '', 10);
    if (Number.isFinite(py) && Number.isFinite(pm) && Number.isFinite(pd)) {
      return new Date(py, pm - 1, pd);
    }
    return null;
  });

  // Backend query window — give the user the full month plus a generous
  // pad so drawer navigation past month boundaries stays cached.
  const queryStart = useMemo(
    () => addDays(monthAnchor, -PAST_LOOKBACK_DAYS),
    [monthAnchor],
  );
  const queryEnd = useMemo(
    () => addDays(monthAnchor, FUTURE_HORIZON_DAYS),
    [monthAnchor],
  );
  const typesArray = useMemo(() => Array.from(selectedTypes).sort(), [selectedTypes]);

  const { data, isLoading, isError, refetch } = useCalendarEvents({
    start: queryStart,
    end: queryEnd,
    ...(typesArray.length > 0 ? { types: typesArray } : {}),
  });

  // Bucket events by ISO date for the grid (O(N) once per query). Agenda
  // view reuses the flat list, so we keep both shapes around.
  const { eventsByDate, eventsFlat } = useMemo(() => {
    const byDate = new Map<string, CalendarEvent[]>();
    const flat: CalendarEvent[] = [];
    for (const evt of data?.data ?? []) {
      flat.push(evt);
      const key = isoKey(evt.eventDate);
      const bucket = byDate.get(key);
      if (bucket) bucket.push(evt);
      else byDate.set(key, [evt]);
    }
    return { eventsByDate: byDate, eventsFlat: flat };
  }, [data]);

  const eventsForOpenDate: readonly CalendarEvent[] = useMemo(() => {
    if (!openDate) return [];
    return eventsByDate.get(isoKey(openDate)) ?? [];
  }, [openDate, eventsByDate]);

  const isPastDay = (d: Date): boolean => d.getTime() < today.getTime();

  const handleNavigateMonth = (offset: number): void => {
    setMonthAnchor((cur) => addMonths(cur, offset));
  };

  const handleJumpToday = (): void => {
    setMonthAnchor(startOfMonth(today));
  };

  const handleDayClick = (d: Date): void => {
    setOpenDate(d);
    // Persist into URL so deep-linking + browser-back works.
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      next.set('date', isoKey(d));
      return next;
    });
  };

  const handleDrawerClose = (): void => {
    setOpenDate(null);
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      next.delete('date');
      return next;
    });
  };

  const handleNavigateDay = (offset: number): void => {
    if (!openDate) return;
    const next = addDays(openDate, offset);
    setOpenDate(next);
    setSearchParams((prev) => {
      const params = new URLSearchParams(prev);
      params.set('date', isoKey(next));
      return params;
    });
    // Keep grid anchor in sync if drawer crosses month boundary.
    if (next.getMonth() !== monthAnchor.getMonth() || next.getFullYear() !== monthAnchor.getFullYear()) {
      setMonthAnchor(startOfMonth(next));
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        monthAnchor={monthAnchor}
        onPrev={() => handleNavigateMonth(-1)}
        onNext={() => handleNavigateMonth(1)}
        onJumpToday={handleJumpToday}
      />

      <div className="flex flex-wrap items-center justify-between gap-3">
        <EventTypeFilter selected={selectedTypes} onChange={setSelectedTypes} />
        <p className="text-xs text-stone-500">
          🟢 財報 · 🔵 總經 · 🟣 產業 · 過去事件以淡色顯示
        </p>
      </div>

      {isLoading ? (
        <PageState>
          <LoadingSpinner label="行事曆載入中…" />
        </PageState>
      ) : isError ? (
        <PageState>
          <p className="text-sm text-rose-600">無法載入行事曆。</p>
          <button
            type="button"
            onClick={() => void refetch()}
            className="rounded-md border border-stone-300 px-3 py-1 text-xs text-stone-700 hover:bg-stone-100"
          >
            重試
          </button>
        </PageState>
      ) : (
        <ResponsiveCalendar
          monthAnchor={monthAnchor}
          today={today}
          eventsByDate={eventsByDate}
          eventsFlat={eventsFlat}
          onDayClick={handleDayClick}
        />
      )}

      {openDate && (
        <EventDrawer
          date={openDate}
          events={eventsForOpenDate}
          isPast={isPastDay(openDate)}
          onClose={handleDrawerClose}
          onNavigateDay={handleNavigateDay}
        />
      )}
    </div>
  );
}

function PageState({ children }: { children: ReactNode }): JSX.Element {
  return (
    <div className="flex min-h-[40vh] flex-col items-center justify-center gap-3 rounded-lg border border-stone-200 bg-white p-6 text-center">
      {children}
    </div>
  );
}

function PageHeader({
  monthAnchor,
  onPrev,
  onNext,
  onJumpToday,
}: {
  monthAnchor: Date;
  onPrev: () => void;
  onNext: () => void;
  onJumpToday: () => void;
}): JSX.Element {
  return (
    <header className="flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-stone-900">行事曆</h1>
        <p className="text-xs text-stone-500">
          個股財報 · 美國總經數據 · 產業催化劑。daily_update 每日同步。
        </p>
      </div>
      <div
        role="toolbar"
        aria-label="月份切換"
        className="flex items-center gap-1"
      >
        <button
          type="button"
          aria-label="前一個月"
          onClick={onPrev}
          className="rounded-md border border-stone-300 px-2 py-1 text-sm text-stone-700 hover:bg-stone-100"
        >
          ←
        </button>
        <span
          aria-live="polite"
          data-testid="calendar-month-label"
          className="min-w-[7rem] text-center text-sm font-semibold text-stone-900"
        >
          {monthAnchor.getFullYear()} 年 {monthAnchor.getMonth() + 1} 月
        </span>
        <button
          type="button"
          aria-label="下一個月"
          onClick={onNext}
          className="rounded-md border border-stone-300 px-2 py-1 text-sm text-stone-700 hover:bg-stone-100"
        >
          →
        </button>
        <button
          type="button"
          onClick={onJumpToday}
          className="ml-2 rounded-md border border-stone-300 px-2 py-1 text-xs text-stone-700 hover:bg-stone-100"
        >
          今日
        </button>
      </div>
    </header>
  );
}

function ResponsiveCalendar({
  monthAnchor,
  today,
  eventsByDate,
  eventsFlat,
  onDayClick,
}: {
  monthAnchor: Date;
  today: Date;
  eventsByDate: ReadonlyMap<string, readonly CalendarEvent[]>;
  eventsFlat: readonly CalendarEvent[];
  onDayClick: (d: Date) => void;
}): JSX.Element {
  return (
    <>
      <div className="hidden lg:block">
        <MonthGrid
          monthAnchor={monthAnchor}
          today={today}
          eventsByDate={eventsByDate}
          onDayClick={onDayClick}
        />
      </div>
      <div className="lg:hidden">
        <AgendaList events={eventsFlat} today={today} onDayClick={onDayClick} />
      </div>
    </>
  );
}
