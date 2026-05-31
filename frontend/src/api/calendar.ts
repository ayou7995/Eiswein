// Catalyst Calendar — single read endpoint backing the 行事曆 page,
// the MarketOverview "this week's data" banner, and the TickerDetail
// "next catalyst" chip. Backend returns events sorted by
// (event_date, event_time, type) so we don't re-sort client-side.

import { z } from 'zod';
import { apiRequest } from './client';

export const eventTypeSchema = z.enum(['earnings', 'macro', 'industry']);
export type EventType = z.infer<typeof eventTypeSchema>;

// Confidence levels emitted by the Gemini-backed industry feeder.
// Used to render solid / dashed / dotted borders on the event chip
// so the operator can spot "this is just an LLM guess" without
// clicking through.
export const industryConfidenceSchema = z.enum([
  'confirmed',
  'estimated',
  'uncertain',
]);
export type IndustryConfidence = z.infer<typeof industryConfidenceSchema>;

export const calendarEventSchema = z.object({
  id: z.number().int().nonnegative(),
  event_date: z.string(), // ISO "YYYY-MM-DD"
  event_time: z.string().nullable(),
  type: eventTypeSchema,
  ticker_symbol: z.string().nullable(),
  title: z.string(),
  // Payload is event-type specific. Known keys:
  //   * earnings: time_marker, consensus_eps
  //   * macro: note
  //   * industry (Gemini-sourced): confidence, source_url,
  //     last_verified_at (ISO datetime), end_date (ISO YYYY-MM-DD), notes
  //   * industry (yaml-sourced): tags
  // Treated as opaque here, parsed in the rendering layer.
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

// --- Industry sync (Gemini) status + manual trigger -------------------

export interface IndustryPayload {
  confidence: IndustryConfidence | null;
  sourceUrl: string | null;
  lastVerifiedAt: Date | null;
  endDate: Date | null;
  notes: string | null;
  tags: readonly string[] | null;
}

// Pulls the Gemini-related keys out of a free-form payload dict.
// Defensive — events curated via the YAML feeder won't have these
// fields, and a forward-compatible LLM may add unknown keys we'd want
// to surface later.
export function extractIndustryPayload(
  payload: Record<string, unknown> | null,
): IndustryPayload {
  const confidence = (() => {
    const raw = payload?.['confidence'];
    return typeof raw === 'string' &&
      (raw === 'confirmed' || raw === 'estimated' || raw === 'uncertain')
      ? raw
      : null;
  })();
  const sourceUrl =
    typeof payload?.['source_url'] === 'string'
      ? (payload['source_url'] as string)
      : null;
  const lastVerifiedAt = (() => {
    const raw = payload?.['last_verified_at'];
    if (typeof raw !== 'string') return null;
    const parsed = new Date(raw);
    return Number.isNaN(parsed.getTime()) ? null : parsed;
  })();
  const endDate = (() => {
    const raw = payload?.['end_date'];
    if (typeof raw !== 'string') return null;
    return parseIsoDate(raw);
  })();
  const notes =
    typeof payload?.['notes'] === 'string' ? (payload['notes'] as string) : null;
  const tags = Array.isArray(payload?.['tags'])
    ? (payload?.['tags'] as unknown[]).filter(
        (item): item is string => typeof item === 'string',
      )
    : null;
  return { confidence, sourceUrl, lastVerifiedAt, endDate, notes, tags };
}

// Days since ``last_verified_at``. Returns ``null`` when the event
// predates the Gemini feeder (e.g. yaml-curated rows) — UI treats
// that as "not stale" rather than "always stale".
export function daysSinceVerified(payload: IndustryPayload): number | null {
  if (!payload.lastVerifiedAt) return null;
  const diffMs = Date.now() - payload.lastVerifiedAt.getTime();
  return Math.max(0, Math.floor(diffMs / (24 * 60 * 60 * 1000)));
}

const industrySyncStatusSchema = z.object({
  last_sync_at: z.string().nullable(),
  stale_days_threshold: z.number().int().positive(),
});

export interface IndustrySyncStatusResult {
  lastSyncAt: Date | null;
  staleDaysThreshold: number;
}

const industrySyncPromptSchema = z.object({
  prompt: z.string(),
  as_of: z.string(),
});

export interface IndustrySyncPromptResult {
  prompt: string;
  asOf: Date;
}

const industrySyncImportSchema = z.object({
  parsed_count: z.number().int().nonnegative(),
  rows_upserted: z.number().int().nonnegative(),
});

export interface IndustrySyncImportResult {
  parsedCount: number;
  rowsUpserted: number;
}

export async function getIndustrySyncStatus(): Promise<IndustrySyncStatusResult> {
  const raw = await apiRequest('/api/v1/calendar/industry-sync/status', {
    method: 'GET',
    schema: industrySyncStatusSchema,
  });
  return {
    lastSyncAt: raw.last_sync_at ? new Date(raw.last_sync_at) : null,
    staleDaysThreshold: raw.stale_days_threshold,
  };
}

export async function getIndustrySyncPrompt(): Promise<IndustrySyncPromptResult> {
  const raw = await apiRequest('/api/v1/calendar/industry-sync/prompt', {
    method: 'GET',
    schema: industrySyncPromptSchema,
  });
  return { prompt: raw.prompt, asOf: parseIsoDate(raw.as_of) };
}

export async function importIndustryEvents(
  jsonText: string,
): Promise<IndustrySyncImportResult> {
  const raw = await apiRequest('/api/v1/calendar/industry-sync/import', {
    method: 'POST',
    body: { json_text: jsonText },
    schema: industrySyncImportSchema,
  });
  return {
    parsedCount: raw.parsed_count,
    rowsUpserted: raw.rows_upserted,
  };
}
