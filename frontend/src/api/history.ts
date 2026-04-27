import { z } from 'zod';
import { apiRequest } from './client';

// /history/market-posture — list of daily snapshots (oldest → newest).
// Date arrives as a YYYY-MM-DD string; keep as string and let the chart
// layer decide on formatting.
export const postureHistoryItemSchema = z.object({
  date: z.string(),
  posture: z.enum(['offensive', 'normal', 'defensive']),
  regime_green_count: z.number().int().nonnegative(),
  regime_red_count: z.number().int().nonnegative(),
  regime_yellow_count: z.number().int().nonnegative(),
  // Optional + default: older snapshots predate this column. Keeps
  // backward compat without raising a SchemaValidationError on legacy data.
  indicator_version: z.string().optional().default(''),
  // SPY close + per-indicator vote map for the price-overlay chart and
  // hover breakdown. Both optional so legacy responses still validate.
  spy_close: z.number().nullable().optional().default(null),
  // SPX 50/200-day SMAs (proxied via SPY) for the auxiliary trend
  // overlay. Null on early dates where the rolling window isn't full.
  spy_ma50: z.number().nullable().optional().default(null),
  spy_ma200: z.number().nullable().optional().default(null),
  regime_signals: z.record(z.string()).optional().default({}),
});
export type PostureHistoryItem = z.infer<typeof postureHistoryItemSchema>;

export const postureHistoryResponseSchema = z.object({
  data: z.array(postureHistoryItemSchema),
  total: z.number().int().nonnegative(),
  has_more: z.boolean(),
});
export type PostureHistoryResponse = z.infer<typeof postureHistoryResponseSchema>;

export const accuracyBucketSchema = z.object({
  total: z.number().int().nonnegative(),
  correct: z.number().int().nonnegative(),
  accuracy_pct: z.number(),
});
export type AccuracyBucket = z.infer<typeof accuracyBucketSchema>;

export const signalAccuracyHorizonSchema = z.union([
  z.literal(5),
  z.literal(20),
  z.literal(60),
  z.literal(120),
]);
export type SignalAccuracyHorizon = z.infer<typeof signalAccuracyHorizonSchema>;

export const SIGNAL_ACCURACY_HORIZONS: readonly SignalAccuracyHorizon[] = [
  5, 20, 60, 120,
];

export const signalAccuracyBaselineSchema = z.object({
  total: z.number().int().nonnegative(),
  spy_up_count: z.number().int().nonnegative(),
  spy_up_pct: z.number(),
});
export type SignalAccuracyBaseline = z.infer<typeof signalAccuracyBaselineSchema>;

export const signalAccuracyResponseSchema = z.object({
  symbol: z.string(),
  horizon: z.number().int(),
  total_signals: z.number().int().nonnegative(),
  correct: z.number().int().nonnegative(),
  accuracy_pct: z.number(),
  by_action: z.record(accuracyBucketSchema),
  baseline: signalAccuracyBaselineSchema,
});
export type SignalAccuracyResponse = z.infer<typeof signalAccuracyResponseSchema>;

export const postureAccuracyBucketSchema = z.object({
  total: z.number().int().nonnegative(),
  correct: z.number().int().nonnegative(),
  accuracy_pct: z.number(),
});
export type PostureAccuracyBucket = z.infer<typeof postureAccuracyBucketSchema>;

export const postureAccuracyResponseSchema = z.object({
  horizon: z.number().int(),
  days: z.number().int().nullable(),
  total_signals: z.number().int().nonnegative(),
  correct: z.number().int().nonnegative(),
  accuracy_pct: z.number(),
  by_posture: z.record(postureAccuracyBucketSchema),
  baseline: signalAccuracyBaselineSchema,
});
export type PostureAccuracyResponse = z.infer<typeof postureAccuracyResponseSchema>;

export function postureAccuracy(
  horizon: SignalAccuracyHorizon,
  days?: number,
): Promise<PostureAccuracyResponse> {
  const search = new URLSearchParams({ horizon: String(horizon) });
  if (days !== undefined) search.set('days', String(days));
  return apiRequest(`/api/v1/history/posture-accuracy?${search.toString()}`, {
    method: 'GET',
    schema: postureAccuracyResponseSchema,
  });
}

export const tickerSignalPointSchema = z.object({
  date: z.string(),
  action: z.string(),
  close: z.number(),
});
export type TickerSignalPoint = z.infer<typeof tickerSignalPointSchema>;

export const tickerSignalsResponseSchema = z.object({
  symbol: z.string(),
  data: z.array(tickerSignalPointSchema),
});
export type TickerSignalsResponse = z.infer<typeof tickerSignalsResponseSchema>;

export function tickerSignalsHistory(
  symbol: string,
  days: number,
): Promise<TickerSignalsResponse> {
  const search = new URLSearchParams({
    symbol,
    days: String(days),
  });
  return apiRequest(`/api/v1/history/ticker-signals?${search.toString()}`, {
    method: 'GET',
    schema: tickerSignalsResponseSchema,
  });
}

export const decisionItemSchema = z.object({
  trade_id: z.number().int().nonnegative(),
  trade_date: z.string(),
  symbol: z.string(),
  side: z.enum(['buy', 'sell']),
  shares: z.string(),
  price: z.string(),
  eiswein_action: z.string().nullable(),
  matched_recommendation: z.boolean().nullable(),
});
export type DecisionItem = z.infer<typeof decisionItemSchema>;

export const decisionHistoryResponseSchema = z.object({
  data: z.array(decisionItemSchema),
  total: z.number().int().nonnegative(),
  has_more: z.boolean(),
});
export type DecisionHistoryResponse = z.infer<typeof decisionHistoryResponseSchema>;

export function marketPostureHistory(days: number): Promise<PostureHistoryResponse> {
  const search = new URLSearchParams({ days: String(days) });
  return apiRequest(`/api/v1/history/market-posture?${search.toString()}`, {
    method: 'GET',
    schema: postureHistoryResponseSchema,
  });
}

export function signalAccuracy(
  symbol: string,
  horizon: SignalAccuracyHorizon,
  days?: number,
): Promise<SignalAccuracyResponse> {
  const search = new URLSearchParams({
    symbol,
    horizon: String(horizon),
  });
  if (days !== undefined) search.set('days', String(days));
  return apiRequest(`/api/v1/history/signal-accuracy?${search.toString()}`, {
    method: 'GET',
    schema: signalAccuracyResponseSchema,
  });
}

export function decisions(limit: number): Promise<DecisionHistoryResponse> {
  const search = new URLSearchParams({ limit: String(limit) });
  return apiRequest(`/api/v1/history/decisions?${search.toString()}`, {
    method: 'GET',
    schema: decisionHistoryResponseSchema,
  });
}
