import { z } from 'zod';
import { apiRequest } from './client';

export const dataStatusSchema = z.enum(['pending', 'ready', 'failed', 'delisted']);
export type DataStatus = z.infer<typeof dataStatusSchema>;

// Dates come from the backend as ISO strings (naive UTC). Kept as strings
// here so the schema's input and output shapes match — apiRequest requires
// that. Callers format/parse via the helpers below.
export const watchlistItemSchema = z.object({
  symbol: z.string(),
  data_status: dataStatusSchema,
  added_at: z.string(),
  last_refresh_at: z.string().nullable(),
});
export type WatchlistItemRaw = z.infer<typeof watchlistItemSchema>;

export interface WatchlistItem {
  symbol: string;
  dataStatus: DataStatus;
  addedAt: Date;
  lastRefreshAt: Date | null;
}

function toWatchlistItem(raw: WatchlistItemRaw): WatchlistItem {
  return {
    symbol: raw.symbol,
    dataStatus: raw.data_status,
    addedAt: new Date(raw.added_at),
    lastRefreshAt: raw.last_refresh_at ? new Date(raw.last_refresh_at) : null,
  };
}

export const watchlistListResponseSchema = z.object({
  data: z.array(watchlistItemSchema),
  total: z.number().int().nonnegative(),
  has_more: z.boolean(),
});

export const watchlistCreateResponseSchema = z.object({
  data: watchlistItemSchema,
});

export const okResponseSchema = z.object({ ok: z.literal(true) });

export const tickerStatusSchema = z.object({
  symbol: z.string(),
  data_status: dataStatusSchema,
  last_refresh_at: z.string().nullable(),
});

export interface TickerStatus {
  symbol: string;
  dataStatus: DataStatus;
  lastRefreshAt: Date | null;
}

export interface WatchlistListResult {
  data: WatchlistItem[];
  total: number;
  hasMore: boolean;
}

export async function listWatchlist(): Promise<WatchlistListResult> {
  const raw = await apiRequest('/api/v1/watchlist', {
    method: 'GET',
    schema: watchlistListResponseSchema,
  });
  return {
    data: raw.data.map(toWatchlistItem),
    total: raw.total,
    hasMore: raw.has_more,
  };
}

export async function addToWatchlist(symbol: string): Promise<WatchlistItem> {
  const raw = await apiRequest('/api/v1/watchlist', {
    method: 'POST',
    body: { symbol },
    schema: watchlistCreateResponseSchema,
  });
  return toWatchlistItem(raw.data);
}

export function removeFromWatchlist(symbol: string): Promise<z.infer<typeof okResponseSchema>> {
  return apiRequest(`/api/v1/watchlist/${encodeURIComponent(symbol)}`, {
    method: 'DELETE',
    schema: okResponseSchema,
  });
}

export async function getTickerStatus(symbol: string): Promise<TickerStatus> {
  const raw = await apiRequest(`/api/v1/ticker/${encodeURIComponent(symbol)}?only_status=1`, {
    method: 'GET',
    schema: tickerStatusSchema,
  });
  return {
    symbol: raw.symbol,
    dataStatus: raw.data_status,
    lastRefreshAt: raw.last_refresh_at ? new Date(raw.last_refresh_at) : null,
  };
}
