import { useMemo } from 'react';
import { Link } from 'react-router-dom';
import { formatIsoDate, type CalendarEvent } from '../api/calendar';
import { useCalendarEvents } from '../hooks/useCalendar';
import { ROUTES } from '../lib/constants';

interface NextCatalystChipProps {
  symbol: string;
}

// Forward window — we want to surface "next earnings" without leaving
// the operator with a stale 9-month-old chip if a company hasn't been
// scheduled yet (yfinance returns up to a year for most names).
const HORIZON_DAYS = 180;

const TYPE_LABEL: Record<CalendarEvent['type'], string> = {
  earnings: '財報',
  macro: '總經',
  industry: '產業',
};

const TYPE_TINT: Record<CalendarEvent['type'], string> = {
  earnings: 'border-emerald-300 bg-emerald-50 text-emerald-800',
  macro: 'border-sky-300 bg-sky-50 text-sky-800',
  industry: 'border-violet-300 bg-violet-50 text-violet-800',
};

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

function daysBetween(from: Date, to: Date): number {
  const ms = startOfDay(to).getTime() - startOfDay(from).getTime();
  return Math.round(ms / (24 * 60 * 60 * 1000));
}

// Right-side header chip on TickerDetail showing the next upcoming
// catalyst. Earnings is the most common case (yfinance.calendar). For
// tickers without an upcoming event in the window the chip renders
// nothing so the header layout doesn't shift around an absent piece
// of data.
export function NextCatalystChip({ symbol }: NextCatalystChipProps): JSX.Element | null {
  const today = useMemo(() => startOfDay(new Date()), []);
  const end = useMemo(() => addDays(today, HORIZON_DAYS), [today]);
  const { data, isLoading } = useCalendarEvents({
    start: today,
    end,
    tickers: [symbol],
  });

  if (isLoading || !data) return null;

  // Find earliest ticker-tied event (skip macro entries that the
  // ticker filter intentionally lets through — those are not catalysts
  // for THIS symbol specifically).
  const upcoming = data.data
    .filter((evt) => evt.tickerSymbol === symbol.toUpperCase())
    .sort((a, b) => a.eventDate.getTime() - b.eventDate.getTime())[0];

  if (!upcoming) return null;

  const days = daysBetween(today, upcoming.eventDate);
  const tint = TYPE_TINT[upcoming.type];
  const label = TYPE_LABEL[upcoming.type];
  const daysLabel = days === 0 ? '今日' : `${days}d`;
  const marker = upcoming.eventTime ? ` ${upcoming.eventTime}` : '';

  return (
    <Link
      to={`${ROUTES.CALENDAR}?date=${formatIsoDate(upcoming.eventDate)}`}
      data-testid="next-catalyst-chip"
      aria-label={`下次催化劑:${upcoming.title} (${daysLabel} 後)`}
      className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium ${tint} hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500`}
    >
      <span aria-hidden="true">📅</span>
      <span>{daysLabel}</span>
      <span aria-hidden="true">·</span>
      <span>
        {label}
        {marker}
      </span>
    </Link>
  );
}
