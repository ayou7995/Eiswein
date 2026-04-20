import { z } from 'zod';
import { apiRequest } from './client';

export const signalToneSchema = z.enum(['green', 'yellow', 'red', 'neutral']);
export type SignalToneCode = z.infer<typeof signalToneSchema>;

export const indicatorResultSchema = z.object({
  name: z.string(),
  value: z.number().nullable(),
  signal: signalToneSchema,
  data_sufficient: z.boolean(),
  short_label: z.string(),
  detail: z.record(z.unknown()),
  indicator_version: z.string(),
});

export type IndicatorResult = z.infer<typeof indicatorResultSchema>;

export const tickerIndicatorsResponseSchema = z.object({
  symbol: z.string(),
  date: z.string(),
  timezone: z.string(),
  indicator_version: z.string(),
  indicators: z.record(indicatorResultSchema),
});

export type TickerIndicatorsResponse = z.infer<typeof tickerIndicatorsResponseSchema>;

export function fetchTickerIndicators(symbol: string): Promise<TickerIndicatorsResponse> {
  return apiRequest(`/api/v1/ticker/${encodeURIComponent(symbol)}/indicators`, {
    method: 'GET',
    schema: tickerIndicatorsResponseSchema,
  });
}
