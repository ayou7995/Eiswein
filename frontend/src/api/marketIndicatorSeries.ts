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
      // ma50 / ma200 can be null on the leading bars when the display
      // window is wider than the MA warm-up (e.g. 2Y view starts before
      // the 200-bar warmup completes).
      ma50: z.number().nullable(),
      ma200: z.number().nullable(),
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
      // OHLCV per day — accepted as nullable+optional so a NaN-tripping
      // bar (encoded as null by the backend's _round_or_none helper)
      // doesn't fail the whole response. Chart filters them out.
      open: z.number().nullable().optional(),
      high: z.number().nullable().optional(),
      low: z.number().nullable().optional(),
      close: z.number().nullable().optional(),
      volume: z.number().nullable().optional(),
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
      // ma20 can be null on the leading bars when the display window is
      // wider than the 20-bar SMA warm-up.
      ma20: z.number().nullable(),
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

// Range options (1M / 3M / 6M / 1Y / 2Y) mapped to trading days. Server
// validates 21 ≤ days ≤ 1260, so any of these is accepted.
export const MARKET_INDICATOR_RANGES = [
  { key: '1M' as const, days: 21, label: '1 月' },
  { key: '3M' as const, days: 60, label: '3 月' },
  { key: '6M' as const, days: 126, label: '6 月' },
  { key: '1Y' as const, days: 252, label: '1 年' },
  { key: '2Y' as const, days: 504, label: '2 年' },
] as const;

export type MarketIndicatorRangeKey = (typeof MARKET_INDICATOR_RANGES)[number]['key'];

// Per-indicator default range — picked to match the indicator's
// timeframe horizon (short → 1M, mid → 3M, long → 1Y) so the chart's
// default window matches what the operator is being asked to judge.
export const DEFAULT_RANGE_BY_INDICATOR: Record<MarketIndicatorSeriesName, MarketIndicatorRangeKey> = {
  // Short-term tactical indicators
  vix: '1M',
  ad_day: '1M',
  // Mid-term trend
  spx_ma: '3M',
  // Long-term macro
  yield_spread: '1Y',
  dxy: '1Y',
  fed_rate: '1Y',
};

export function getMarketIndicatorSeries(
  name: MarketIndicatorSeriesName,
  days?: number,
): Promise<MarketIndicatorSeriesResponse> {
  const path =
    days === undefined
      ? `/api/v1/market/indicator/${name}/series`
      : `/api/v1/market/indicator/${name}/series?days=${days}`;
  return apiRequest(path, {
    method: 'GET',
    schema: marketIndicatorSeriesResponseSchema,
  });
}
