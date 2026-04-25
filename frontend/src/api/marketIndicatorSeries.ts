import { z } from 'zod';
import { apiRequest } from './client';

export const marketIndicatorSeriesNameSchema = z.enum([
  'spx_ma',
  'vix',
  'yield_spread',
  'ad_day',
  'dxy',
  'fed_rate',
]);
export type MarketIndicatorSeriesName = z.infer<typeof marketIndicatorSeriesNameSchema>;

const spxMaResponseSchema = z.object({
  indicator: z.literal('spx_ma'),
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

const vixResponseSchema = z.object({
  indicator: z.literal('vix'),
  series: z.array(
    z.object({
      date: z.string(),
      level: z.number(),
    }),
  ),
  summary_zh: z.string(),
  current: z.object({
    level: z.number(),
    ten_day_change: z.number(),
    trend: z.enum(['rising', 'falling', 'flat']),
    zone: z.enum(['low', 'normal', 'elevated', 'panic']),
    percentile_1y: z.number(),
  }),
  thresholds: z.object({
    low: z.number(),
    normal_high: z.number(),
    elevated_high: z.number(),
  }),
});

const yieldSpreadResponseSchema = z.object({
  indicator: z.literal('yield_spread'),
  series: z.array(
    z.object({
      date: z.string(),
      spread: z.number(),
      ten_year: z.number(),
      two_year: z.number(),
    }),
  ),
  summary_zh: z.string(),
  current: z.object({
    spread: z.number(),
    ten_year: z.number(),
    two_year: z.number(),
    days_since_inversion: z.number().nullable(),
    last_inversion_end: z.string().nullable(),
  }),
});

export const adDayClassificationSchema = z.enum(['accum', 'distrib', 'neutral']);
export type AdDayClassification = z.infer<typeof adDayClassificationSchema>;

const adDayResponseSchema = z.object({
  indicator: z.literal('ad_day'),
  series: z.array(
    z.object({
      date: z.string(),
      classification: adDayClassificationSchema,
      spx_change: z.number(),
      volume_ratio: z.number(),
    }),
  ),
  summary_zh: z.string(),
  current: z.object({
    accum_count_25d: z.number(),
    distrib_count_25d: z.number(),
    net_25d: z.number(),
    accum_count_5d: z.number(),
    distrib_count_5d: z.number(),
    net_5d: z.number(),
  }),
});

const dxyTrendResponseSchema = z.object({
  indicator: z.literal('dxy'),
  series: z.array(
    z.object({
      date: z.string(),
      level: z.number(),
      ma20: z.number(),
    }),
  ),
  summary_zh: z.string(),
  current: z.object({
    level: z.number(),
    ma20: z.number(),
    streak_rising: z.boolean(),
    streak_falling: z.boolean(),
    streak_days: z.number(),
    ma20_change_5d: z.number(),
  }),
});

const fedFundsResponseSchema = z.object({
  indicator: z.literal('fed_rate'),
  series: z.array(
    z.object({
      date: z.string(),
      rate: z.number(),
    }),
  ),
  summary_zh: z.string(),
  current: z.object({
    current_rate: z.number(),
    prior_30d_rate: z.number(),
    delta_30d: z.number(),
    days_since_last_change: z.number().nullable(),
    last_change_date: z.string().nullable(),
    last_change_direction: z.enum(['hike', 'cut']).nullable(),
  }),
});

export const marketIndicatorSeriesResponseSchema = z.discriminatedUnion('indicator', [
  spxMaResponseSchema,
  vixResponseSchema,
  yieldSpreadResponseSchema,
  adDayResponseSchema,
  dxyTrendResponseSchema,
  fedFundsResponseSchema,
]);

export type MarketIndicatorSeriesResponse = z.infer<typeof marketIndicatorSeriesResponseSchema>;
export type SpxMaSeriesResponse = z.infer<typeof spxMaResponseSchema>;
export type VixSeriesResponse = z.infer<typeof vixResponseSchema>;
export type YieldSpreadSeriesResponse = z.infer<typeof yieldSpreadResponseSchema>;
export type AdDaySeriesResponse = z.infer<typeof adDayResponseSchema>;
export type DxyTrendSeriesResponse = z.infer<typeof dxyTrendResponseSchema>;
export type FedFundsSeriesResponse = z.infer<typeof fedFundsResponseSchema>;

export function getMarketIndicatorSeries(
  name: MarketIndicatorSeriesName,
): Promise<MarketIndicatorSeriesResponse> {
  return apiRequest(`/api/v1/market/indicator/${name}/series`, {
    method: 'GET',
    schema: marketIndicatorSeriesResponseSchema,
  });
}
