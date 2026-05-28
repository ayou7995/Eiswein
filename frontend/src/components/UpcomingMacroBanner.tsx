import { useMemo } from 'react';
import { Link } from 'react-router-dom';
import { formatIsoDate } from '../api/calendar';
import { useCalendarEvents } from '../hooks/useCalendar';
import { ROUTES } from '../lib/constants';

// Compact strip at the top of MarketOverview listing macro events
// (CPI / PCE / PPI / FOMC / NFP / PMI) in the next 7 days. Clicking
// any entry routes to /calendar with that date pre-opened so the
// operator gets context in one tap.
//
// Returns null (no banner) when no macro events land in the window;
// the page should not pay vertical space for an empty state.

const WINDOW_DAYS = 7;
const WEEKDAY_ABBR: readonly string[] = ['週日', '週一', '週二', '週三', '週四', '週五', '週六'];

function startOfDay(date: Date): Date {
  const out = new Date(date);
  out.setHours(0, 0, 0, 0);
  return out;
}

function addDays(date: Date, offset: number): Date {
  const out = new Date(date);
  out.setDate(out.getDate() + offset);
  return out;
}

export function UpcomingMacroBanner(): JSX.Element | null {
  const today = useMemo(() => startOfDay(new Date()), []);
  const end = useMemo(() => addDays(today, WINDOW_DAYS), [today]);
  const { data, isLoading } = useCalendarEvents({
    start: today,
    end,
    types: ['macro'],
  });

  if (isLoading) return null;
  const events = data?.data ?? [];
  if (events.length === 0) return null;

  return (
    <section
      aria-label="本週重大數據"
      data-testid="upcoming-macro-banner"
      className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border border-sky-200 bg-sky-50 px-3 py-2 text-xs text-sky-900"
    >
      <span className="font-semibold tracking-wide">📅 本週重大數據</span>
      <ul role="list" className="flex flex-wrap items-center gap-x-3 gap-y-1">
        {events.map((evt) => {
          const weekday = WEEKDAY_ABBR[evt.eventDate.getDay()];
          return (
            <li key={evt.id} className="flex items-center gap-1">
              <Link
                to={`${ROUTES.CALENDAR}?date=${formatIsoDate(evt.eventDate)}`}
                className="rounded px-1 hover:bg-sky-100 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500"
              >
                <span className="font-medium">{evt.title.replace(/\s+Release$/u, '')}</span>
                <span className="ml-1 text-sky-700">{weekday}</span>
                {evt.eventTime && (
                  <span className="ml-1 text-sky-500">{evt.eventTime}</span>
                )}
              </Link>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
