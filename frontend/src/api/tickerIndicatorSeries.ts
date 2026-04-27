import { z } from 'zod';
import { apiRequest } from './client';

export const indicatorSeriesNameSchema = z.enum([
  'price_vs_ma',
  'rsi',
  'macd',
  'bollinger',
  'volume_anomaly',
  'relative_strength',
]);
export type IndicatorSeriesName = z.infer<typeof indicatorSeriesNameSchema>;

const priceVsMaResponseSchema = z.object({
  symbol: z.string(),
  indicator: z.literal('price_vs_ma'),
  series: z.array(
    z.object({
      date: z.string(),
      price: z.number(),
      ma50: z.number(),
      ma200: z.number(),
    }),
  ),
  summary_zh: z.string(),
  current: z.object({
    price: z.number(),
    ma50: z.number(),
    ma200: z.number(),
    above_both_days: z.number(),
  }),
});

const rsiResponseSchema = z.object({
  symbol: z.string(),
  indicator: z.literal('rsi'),
  series: z.array(
    z.object({
      date: z.string(),
      daily: z.number(),
      weekly: z.number(),
    }),
  ),
  summary_zh: z.string(),
  current: z.object({
    daily: z.number(),
    weekly: z.number(),
    zone: z.enum(['oversold', 'neutral_weak', 'neutral_strong', 'overbought']),
  }),
  thresholds: z.object({
    oversold: z.literal(30),
    overbought: z.literal(70),
  }),
});

const macdResponseSchema = z.object({
  symbol: z.string(),
  indicator: z.literal('macd'),
  series: z.array(
    z.object({
      date: z.string(),
      macd: z.number(),
      signal: z.number(),
      histogram: z.number(),
    }),
  ),
  summary_zh: z.string(),
  current: z.object({
    macd: z.number(),
    signal: z.number(),
    histogram: z.number(),
    last_cross: z.enum(['golden', 'death']).nullable(),
    bars_since_cross: z.number().nullable(),
  }),
});

const bollingerBandsResponseSchema = z.object({
  symbol: z.string(),
  indicator: z.literal('bollinger'),
  series: z.array(
    z.object({
      date: z.string(),
      price: z.number(),
      upper: z.number(),
      middle: z.number(),
      lower: z.number(),
    }),
  ),
  summary_zh: z.string(),
  current: z.object({
    price: z.number(),
    upper: z.number(),
    middle: z.number(),
    lower: z.number(),
    position: z.number(),
    band_width: z.number(),
    band_width_5d_change: z.number(),
  }),
});

const volumeAnomalyResponseSchema = z.object({
  symbol: z.string(),
  indicator: z.literal('volume_anomaly'),
  series: z.array(
    z.object({
      date: z.string(),
      volume: z.number(),
      price_change_pct: z.number(),
      avg_volume_20d: z.number(),
    }),
  ),
  summary_zh: z.string(),
  current: z.object({
    today_volume: z.number(),
    avg_volume_20d: z.number(),
    ratio: z.number(),
    five_day_avg_ratio: z.number(),
    spike: z.boolean(),
  }),
});

const relativeStrengthResponseSchema = z.object({
  symbol: z.string(),
  indicator: z.literal('relative_strength'),
  series: z.array(
    z.object({
      date: z.string(),
      ticker_cum_return: z.number(),
      spx_cum_return: z.number(),
      diff: z.number(),
    }),
  ),
  summary_zh: z.string(),
  current: z.object({
    ticker_20d_return: z.number(),
    spx_20d_return: z.number(),
    diff_20d: z.number(),
    ticker_60d_return: z.number(),
    spx_60d_return: z.number(),
    diff_60d: z.number(),
  }),
});

export const indicatorSeriesResponseSchema = z.discriminatedUnion('indicator', [
  priceVsMaResponseSchema,
  rsiResponseSchema,
  macdResponseSchema,
  bollingerBandsResponseSchema,
  volumeAnomalyResponseSchema,
  relativeStrengthResponseSchema,
]);

export type IndicatorSeriesResponse = z.infer<
  typeof indicatorSeriesResponseSchema
>;
export type PriceVsMaSeriesResponse = z.infer<typeof priceVsMaResponseSchema>;
export type RsiSeriesResponse = z.infer<typeof rsiResponseSchema>;
export type MacdSeriesResponse = z.infer<typeof macdResponseSchema>;
export type BollingerBandsSeriesResponse = z.infer<
  typeof bollingerBandsResponseSchema
>;
export type VolumeAnomalySeriesResponse = z.infer<
  typeof volumeAnomalyResponseSchema
>;
export type RelativeStrengthSeriesResponse = z.infer<
  typeof relativeStrengthResponseSchema
>;

export function getIndicatorSeries(
  symbol: string,
  name: IndicatorSeriesName,
  days?: number,
): Promise<IndicatorSeriesResponse> {
  const base = `/api/v1/ticker/${encodeURIComponent(symbol)}/indicator/${name}/series`;
  const path = days === undefined ? base : `${base}?days=${days}`;
  return apiRequest(path, {
    method: 'GET',
    schema: indicatorSeriesResponseSchema,
  });
}
