import { z } from 'zod';
import { apiRequest } from './client';

export const priceRangeSchema = z.enum(['1M', '3M', '6M', '1Y', 'ALL']);
export type PriceRange = z.infer<typeof priceRangeSchema>;

export const PRICE_RANGES: readonly PriceRange[] = ['1M', '3M', '6M', '1Y', 'ALL'];

export const priceBarSchema = z.object({
  date: z.string(),
  open: z.number(),
  high: z.number(),
  low: z.number(),
  close: z.number(),
  volume: z.number().int().nonnegative(),
});

export type PriceBar = z.infer<typeof priceBarSchema>;

export const priceHistoryResponseSchema = z.object({
  symbol: z.string(),
  range: priceRangeSchema,
  timezone: z.string(),
  bars: z.array(priceBarSchema),
});

export type PriceHistoryResponse = z.infer<typeof priceHistoryResponseSchema>;

export function fetchTickerPrices(
  symbol: string,
  range: PriceRange,
): Promise<PriceHistoryResponse> {
  const search = new URLSearchParams({ range });
  return apiRequest(
    `/api/v1/ticker/${encodeURIComponent(symbol)}/prices?${search.toString()}`,
    {
      method: 'GET',
      schema: priceHistoryResponseSchema,
    },
  );
}
