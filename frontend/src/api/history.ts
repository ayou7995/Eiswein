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
  z.literal(10),
  z.literal(20),
]);
export type SignalAccuracyHorizon = z.infer<typeof signalAccuracyHorizonSchema>;

export const SIGNAL_ACCURACY_HORIZONS: readonly SignalAccuracyHorizon[] = [5, 10, 20];

export const signalAccuracyResponseSchema = z.object({
  symbol: z.string(),
  horizon: z.number().int(),
  total_signals: z.number().int().nonnegative(),
  correct: z.number().int().nonnegative(),
  accuracy_pct: z.number(),
  by_action: z.record(accuracyBucketSchema),
});
export type SignalAccuracyResponse = z.infer<typeof signalAccuracyResponseSchema>;

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
): Promise<SignalAccuracyResponse> {
  const search = new URLSearchParams({
    symbol,
    horizon: String(horizon),
  });
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
