import { z } from 'zod';
import { apiRequest } from './client';

export const marketIndicatorSeriesNameSchema = z.enum([
  'spx_ma',
  'vix',
  'yield_spread',
  'ad_day',
  'dxy',
  'fed_rate',
  'spx_adx',
  'vix_term',
  'rsp_spy',
  'hyg_ief',
  'skew',
  'unrate',
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

const spxAdxResponseSchema = z.object({
  indicator: z.literal('spx_adx'),
  series: z.array(
    z.object({
      date: z.string(),
      adx: z.number().nullable(),
      plus_di: z.number().nullable(),
      minus_di: z.number().nullable(),
    }),
  ),
  summary_zh: z.string(),
  current: z.object({
    adx: z.number().nullable(),
    plus_di: z.number().nullable(),
    minus_di: z.number().nullable(),
    zone: z.enum(['choppy', 'ambiguous', 'trending', 'unknown']),
    direction: z.enum(['up', 'down', 'unknown']),
  }),
  thresholds: z.object({
    no_trend: z.number(),
    trend: z.number(),
  }),
});

const vixTermResponseSchema = z.object({
  indicator: z.literal('vix_term'),
  series: z.array(
    z.object({
      date: z.string(),
      vix: z.number().nullable(),
      vix3m: z.number().nullable(),
      ratio: z.number().nullable(),
    }),
  ),
  summary_zh: z.string(),
  current: z.object({
    vix: z.number().nullable(),
    vix3m: z.number().nullable(),
    ratio: z.number().nullable(),
    zone: z.enum(['contango', 'flat', 'inverted', 'unknown']),
  }),
  thresholds: z.object({
    contango: z.number(),
    inversion: z.number(),
  }),
});

const rspSpyResponseSchema = z.object({
  indicator: z.literal('rsp_spy'),
  series: z.array(
    z.object({
      date: z.string(),
      rsp: z.number().nullable(),
      spy: z.number().nullable(),
      ratio: z.number().nullable(),
    }),
  ),
  summary_zh: z.string(),
  current: z.object({
    rsp: z.number().nullable(),
    spy: z.number().nullable(),
    ratio: z.number().nullable(),
    slope_20d_pct: z.number().nullable(),
  }),
});

const hygIefResponseSchema = z.object({
  indicator: z.literal('hyg_ief'),
  series: z.array(
    z.object({
      date: z.string(),
      hyg: z.number().nullable(),
      ief: z.number().nullable(),
      ratio: z.number().nullable(),
    }),
  ),
  summary_zh: z.string(),
  current: z.object({
    hyg: z.number().nullable(),
    ief: z.number().nullable(),
    ratio: z.number().nullable(),
    slope_20d_pct: z.number().nullable(),
  }),
});

const skewResponseSchema = z.object({
  indicator: z.literal('skew'),
  series: z.array(
    z.object({
      date: z.string(),
      level: z.number().nullable(),
    }),
  ),
  summary_zh: z.string(),
  current: z.object({
    level: z.number().nullable(),
    ten_day_change: z.number().nullable(),
    zone: z.enum(['normal', 'elevated', 'high', 'unknown']),
    percentile_1y: z.number().nullable(),
  }),
  thresholds: z.object({
    normal_high: z.number(),
    elevated_high: z.number(),
  }),
});

const unrateResponseSchema = z.object({
  indicator: z.literal('unrate'),
  series: z.array(
    z.object({
      date: z.string(),
      rate: z.number().nullable(),
      sahm_value: z.number().nullable(),
    }),
  ),
  summary_zh: z.string(),
  current: z.object({
    current_rate: z.number().nullable(),
    three_month_avg: z.number().nullable(),
    twelve_month_low: z.number().nullable(),
    sahm_value: z.number().nullable(),
    sahm_distance_to_trigger: z.number().nullable(),
    zone: z.enum(['healthy', 'warning', 'recession', 'unknown']),
  }),
  thresholds: z.object({
    warning: z.number(),
    trigger: z.number(),
  }),
});

export const marketIndicatorSeriesResponseSchema = z.discriminatedUnion('indicator', [
  spxMaResponseSchema,
  vixResponseSchema,
  yieldSpreadResponseSchema,
  adDayResponseSchema,
  dxyTrendResponseSchema,
  fedFundsResponseSchema,
  spxAdxResponseSchema,
  vixTermResponseSchema,
  rspSpyResponseSchema,
  hygIefResponseSchema,
  skewResponseSchema,
  unrateResponseSchema,
]);

export type MarketIndicatorSeriesResponse = z.infer<typeof marketIndicatorSeriesResponseSchema>;
export type SpxMaSeriesResponse = z.infer<typeof spxMaResponseSchema>;
export type VixSeriesResponse = z.infer<typeof vixResponseSchema>;
export type YieldSpreadSeriesResponse = z.infer<typeof yieldSpreadResponseSchema>;
export type AdDaySeriesResponse = z.infer<typeof adDayResponseSchema>;
export type DxyTrendSeriesResponse = z.infer<typeof dxyTrendResponseSchema>;
export type FedFundsSeriesResponse = z.infer<typeof fedFundsResponseSchema>;
export type SpxAdxSeriesResponse = z.infer<typeof spxAdxResponseSchema>;
export type VixTermSeriesResponse = z.infer<typeof vixTermResponseSchema>;
export type RspSpySeriesResponse = z.infer<typeof rspSpyResponseSchema>;
export type HygIefSeriesResponse = z.infer<typeof hygIefResponseSchema>;
export type SkewSeriesResponse = z.infer<typeof skewResponseSchema>;
export type UnrateSeriesResponse = z.infer<typeof unrateResponseSchema>;

// Range options mapped to trading days. Server validates 21 ≤ days ≤ 1260
// for the ``days`` param; the ``ALL`` button instead sends ``?range=all``
// which the server treats as the deepest backfill the bootstrap wizard
// offers (5y today).
export const MARKET_INDICATOR_RANGES = [
  { key: '1M' as const, days: 21, label: '1 月' },
  { key: '3M' as const, days: 60, label: '3 月' },
  { key: '6M' as const, days: 126, label: '6 月' },
  { key: '1Y' as const, days: 252, label: '1 年' },
  { key: '2Y' as const, days: 504, label: '2 年' },
  { key: '5Y' as const, days: 1260, label: '5 年' },
  { key: 'ALL' as const, days: null, label: '全部' },
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
  spx_adx: '3M',
  rsp_spy: '3M',
  hyg_ief: '3M',
  // Short-term posture additions (Phase 4 + 5)
  vix_term: '1M',
  skew: '1M',
  // Long-term macro
  yield_spread: '1Y',
  dxy: '1Y',
  fed_rate: '1Y',
  // UNRATE is monthly — 5Y view shows ~1 full cycle of the Sahm Rule.
  unrate: '5Y',
};

export function getMarketIndicatorSeries(
  name: MarketIndicatorSeriesName,
  daysOrAll?: number | 'all',
): Promise<MarketIndicatorSeriesResponse> {
  let path = `/api/v1/market/indicator/${name}/series`;
  if (daysOrAll === 'all') {
    path += '?range=all';
  } else if (daysOrAll !== undefined) {
    path += `?days=${daysOrAll}`;
  }
  return apiRequest(path, {
    method: 'GET',
    schema: marketIndicatorSeriesResponseSchema,
  });
}
