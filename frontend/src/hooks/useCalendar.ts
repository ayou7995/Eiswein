import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import {
  formatIsoDate,
  listCalendarEvents,
  type CalendarEventListResult,
  type EventType,
} from '../api/calendar';

// Calendar events stay fresh for 5 minutes — the underlying table is
// only rewritten once per day by daily_update. Refetch on focus is
// off because navigating away and back shouldn't cost a roundtrip
// (the user is mostly looking at the same month).
const CALENDAR_STALE_MS = 5 * 60 * 1000;

interface CalendarQueryArgs {
  start: Date;
  end: Date;
  types?: readonly EventType[];
  tickers?: readonly string[];
}

function calendarQueryKey(args: CalendarQueryArgs): readonly unknown[] {
  return [
    'calendar',
    'events',
    formatIsoDate(args.start),
    formatIsoDate(args.end),
    // Sort filter values into the cache key so {AAPL, NVDA} and
    // {NVDA, AAPL} hit the same cache entry.
    [...(args.types ?? [])].sort(),
    [...(args.tickers ?? [])].map((t) => t.toUpperCase()).sort(),
  ] as const;
}

export function useCalendarEvents(
  args: CalendarQueryArgs,
): UseQueryResult<CalendarEventListResult> {
  return useQuery({
    queryKey: calendarQueryKey(args),
    queryFn: () => listCalendarEvents(args),
    staleTime: CALENDAR_STALE_MS,
    refetchOnWindowFocus: false,
  });
}
