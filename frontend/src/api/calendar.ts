// Catalyst Calendar — single read endpoint backing the 行事曆 page,
// the MarketOverview "this week's data" banner, and the TickerDetail
// "next catalyst" chip. Backend returns events sorted by
// (event_date, event_time, type) so we don't re-sort client-side.

import { z } from 'zod';
import { apiRequest } from './client';

export const eventTypeSchema = z.enum(['earnings', 'macro', 'industry']);
export type EventType = z.infer<typeof eventTypeSchema>;

export const calendarEventSchema = z.object({
  id: z.number().int().nonnegative(),
  event_date: z.string(), // ISO "YYYY-MM-DD"
  event_time: z.string().nullable(),
  type: eventTypeSchema,
  ticker_symbol: z.string().nullable(),
  title: z.string(),
  // Payload is event-type specific (earnings: time_marker /
  // consensus_eps; macro: note; industry: tags) — treated as opaque
  // here, parsed in the rendering layer.
  payload: z.record(z.string(), z.unknown()).nullable(),
  source: z.string(),
});
export type CalendarEventRaw = z.infer<typeof calendarEventSchema>;

export interface CalendarEvent {
  id: number;
  eventDate: Date;
  eventTime: string | null;
  type: EventType;
  tickerSymbol: string | null;
  title: string;
  payload: Record<string, unknown> | null;
  source: string;
}

export const calendarEventListResponseSchema = z.object({
  data: z.array(calendarEventSchema),
  total: z.number().int().nonnegative(),
  range_start: z.string(),
  range_end: z.string(),
});

export interface CalendarEventListResult {
  data: CalendarEvent[];
  total: number;
  rangeStart: Date;
  rangeEnd: Date;
}

function toCalendarEvent(raw: CalendarEventRaw): CalendarEvent {
  return {
    id: raw.id,
    // Parsing "YYYY-MM-DD" with new Date() is timezone-quirky; build
    // the date in local midnight so day-of-week renders match.
    eventDate: parseIsoDate(raw.event_date),
    eventTime: raw.event_time,
    type: raw.type,
    tickerSymbol: raw.ticker_symbol,
    title: raw.title,
    payload: raw.payload,
    source: raw.source,
  };
}

function parseIsoDate(iso: string): Date {
  const [yearStr, monthStr, dayStr] = iso.split('-');
  const year = Number.parseInt(yearStr ?? '', 10);
  const month = Number.parseInt(monthStr ?? '', 10);
  const day = Number.parseInt(dayStr ?? '', 10);
  return new Date(year, month - 1, day);
}

function toQueryString(params: {
  start: string;
  end: string;
  types?: readonly EventType[];
  tickers?: readonly string[];
}): string {
  const usp = new URLSearchParams();
  usp.set('start', params.start);
  usp.set('end', params.end);
  for (const t of params.types ?? []) usp.append('types', t);
  for (const ticker of params.tickers ?? []) usp.append('tickers', ticker.toUpperCase());
  return usp.toString();
}

export function formatIsoDate(d: Date): string {
  const year = d.getFullYear();
  const month = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

export async function listCalendarEvents(params: {
  start: Date;
  end: Date;
  types?: readonly EventType[];
  tickers?: readonly string[];
}): Promise<CalendarEventListResult> {
  const qsInput: {
    start: string;
    end: string;
    types?: readonly EventType[];
    tickers?: readonly string[];
  } = {
    start: formatIsoDate(params.start),
    end: formatIsoDate(params.end),
  };
  if (params.types) qsInput.types = params.types;
  if (params.tickers) qsInput.tickers = params.tickers;
  const qs = toQueryString(qsInput);
  const raw = await apiRequest(`/api/v1/calendar/events?${qs}`, {
    method: 'GET',
    schema: calendarEventListResponseSchema,
  });
  return {
    data: raw.data.map(toCalendarEvent),
    total: raw.total,
    rangeStart: parseIsoDate(raw.range_start),
    rangeEnd: parseIsoDate(raw.range_end),
  };
}
