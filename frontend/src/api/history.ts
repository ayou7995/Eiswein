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
  // Phase 6 magnitude-weighted: avg % return per signal if you traded
  // the implied position (long on BUY, short on SELL, cash on FLAT).
  // Older snapshots default to 0.
  avg_return_pct: z.number().default(0),
  baseline_avg_return_pct: z.number().default(0),
  delta_vs_baseline: z.number().default(0),
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
  // Phase 6 (2026-06): 3-class baseline so HOLD/WATCH/normal signals
  // have a meaningful comparison. Defaulted to 0 for pre-upgrade snapshots.
  spy_down_count: z.number().int().nonnegative().default(0),
  spy_down_pct: z.number().default(0),
  spy_flat_count: z.number().int().nonnegative().default(0),
  spy_flat_pct: z.number().default(0),
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

// --- /history/event-study ---------------------------------------------------

export const eventStudyHorizonStatSchema = z.object({
  horizon_days: z.number().int().positive(),
  n_events: z.number().int().nonnegative(),
  avg_ar_pct: z.number(),
  stdev_pct: z.number(),
  t_stat: z.number(),
  p_value: z.number(),
});
export type EventStudyHorizonStat = z.infer<typeof eventStudyHorizonStatSchema>;

export const eventStudyBucketSchema = z.object({
  action: z.string(),
  n_events_total: z.number().int().nonnegative(),
  horizons: z.array(eventStudyHorizonStatSchema),
});
export type EventStudyBucket = z.infer<typeof eventStudyBucketSchema>;

export const eventStudyResponseSchema = z.object({
  symbol: z.string(),
  days: z.number().int().nullable(),
  by_action: z.record(eventStudyBucketSchema),
});
export type EventStudyResponse = z.infer<typeof eventStudyResponseSchema>;

export function eventStudy(
  symbol: string,
  days?: number,
): Promise<EventStudyResponse> {
  const search = new URLSearchParams({ symbol });
  if (days !== undefined) search.set('days', String(days));
  return apiRequest(`/api/v1/history/event-study?${search.toString()}`, {
    method: 'GET',
    schema: eventStudyResponseSchema,
  });
}

// --- /history/pnl-simulation -----------------------------------------------

export const pnlTradeSchema = z.object({
  entry_date: z.string(),
  entry_price: z.number(),
  entry_action: z.string(),
  exit_date: z.string(),
  exit_price: z.number(),
  exit_reason: z.string(),
  qty: z.number(),
  pnl_pct: z.number(),
  pnl_abs: z.number(),
  holding_days: z.number().int().nonnegative(),
});
export type PnlTrade = z.infer<typeof pnlTradeSchema>;

export const pnlSummarySchema = z.object({
  starting_capital: z.number(),
  final_value: z.number(),
  total_return_pct: z.number(),
  spy_total_return_pct: z.number(),
  spy_alpha_pct: z.number(),
  stock_total_return_pct: z.number(),
  stock_alpha_pct: z.number(),
  n_trades: z.number().int().nonnegative(),
  n_winners: z.number().int().nonnegative(),
  n_losers: z.number().int().nonnegative(),
  win_rate_pct: z.number(),
  avg_win_pct: z.number(),
  avg_loss_pct: z.number(),
  sharpe_ratio: z.number(),
  max_drawdown_pct: z.number(),
  days_in_market_pct: z.number(),
});
export type PnlSummary = z.infer<typeof pnlSummarySchema>;

export const pnlDailyValueSchema = z.object({
  date: z.string(),
  strategy_value: z.number(),
  spy_baseline_value: z.number(),
  stock_baseline_value: z.number(),
});
export type PnlDailyValue = z.infer<typeof pnlDailyValueSchema>;

export const pnlSimulationResponseSchema = z.object({
  symbol: z.string(),
  days: z.number().int().nullable(),
  summary: pnlSummarySchema,
  trades: z.array(pnlTradeSchema),
  daily_values: z.array(pnlDailyValueSchema),
});
export type PnlSimulationResponse = z.infer<typeof pnlSimulationResponseSchema>;

export function pnlSimulation(
  symbol: string,
  days?: number,
): Promise<PnlSimulationResponse> {
  const search = new URLSearchParams({ symbol });
  if (days !== undefined) search.set('days', String(days));
  return apiRequest(`/api/v1/history/pnl-simulation?${search.toString()}`, {
    method: 'GET',
    schema: pnlSimulationResponseSchema,
  });
}

// --- /history/robustness-check --------------------------------------------

export const robustnessRunSchema = z.object({
  stop_loss_pct: z.number(),
  take_profit_pct: z.number(),
  sizing: z.string(),
  total_return_pct: z.number(),
  spy_alpha_pct: z.number(),
  stock_alpha_pct: z.number(),
  sharpe_ratio: z.number(),
  max_drawdown_pct: z.number(),
  n_trades: z.number().int(),
  win_rate_pct: z.number(),
});
export type RobustnessRun = z.infer<typeof robustnessRunSchema>;

export const robustnessStatSchema = z.object({
  metric: z.string(),
  median: z.number(),
  p10: z.number(),
  p90: z.number(),
  min_value: z.number(),
  max_value: z.number(),
  range_value: z.number(),
  stdev: z.number(),
});
export type RobustnessStat = z.infer<typeof robustnessStatSchema>;

export const robustnessCheckResponseSchema = z.object({
  symbol: z.string(),
  days: z.number().int().nullable(),
  n_runs: z.number().int(),
  baseline_run: robustnessRunSchema,
  runs: z.array(robustnessRunSchema),
  stats: z.record(robustnessStatSchema),
});
export type RobustnessCheckResponse = z.infer<typeof robustnessCheckResponseSchema>;

export function robustnessCheck(
  symbol: string,
  days?: number,
): Promise<RobustnessCheckResponse> {
  const search = new URLSearchParams({ symbol });
  if (days !== undefined) search.set('days', String(days));
  return apiRequest(`/api/v1/history/robustness-check?${search.toString()}`, {
    method: 'GET',
    schema: robustnessCheckResponseSchema,
  });
}

// --- /history/time-split-validation --------------------------------------

export const timeSplitHalfSchema = z.object({
  start_date: z.string(),
  end_date: z.string(),
  n_days: z.number().int(),
  n_snapshots: z.number().int(),
  total_return_pct: z.number(),
  spy_alpha_pct: z.number(),
  stock_alpha_pct: z.number(),
  sharpe_ratio: z.number(),
  max_drawdown_pct: z.number(),
  n_trades: z.number().int(),
  win_rate_pct: z.number(),
});
export type TimeSplitHalf = z.infer<typeof timeSplitHalfSchema>;

export const timeSplitResponseSchema = z.object({
  symbol: z.string(),
  days: z.number().int().nullable(),
  split_pct: z.number().int(),
  split_date: z.string(),
  train: timeSplitHalfSchema,
  test: timeSplitHalfSchema,
  spy_alpha_delta: z.number(),
  stock_alpha_delta: z.number(),
  sharpe_delta: z.number(),
});
export type TimeSplitResponse = z.infer<typeof timeSplitResponseSchema>;

export function timeSplitValidation(
  symbol: string,
  days?: number,
  splitPct?: number,
): Promise<TimeSplitResponse> {
  const search = new URLSearchParams({ symbol });
  if (days !== undefined) search.set('days', String(days));
  if (splitPct !== undefined) search.set('split_pct', String(splitPct));
  return apiRequest(`/api/v1/history/time-split-validation?${search.toString()}`, {
    method: 'GET',
    schema: timeSplitResponseSchema,
  });
}

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

// Per-symbol hit-rate ranking — sorts the watchlist by accuracy_pct over the
// requested window. Backend caps at 20 symbols and runs sub-100ms, so the UI
// can rerun on every range-button switch without debounce.
export const symbolAccuracyEntrySchema = z.object({
  symbol: z.string(),
  total_signals: z.number().int().nonnegative(),
  correct: z.number().int().nonnegative(),
  accuracy_pct: z.number(),
});
export type SymbolAccuracyEntry = z.infer<typeof symbolAccuracyEntrySchema>;

export const symbolAccuracyRankingResponseSchema = z.object({
  horizon: z.number().int(),
  days: z.number().int(),
  data: z.array(symbolAccuracyEntrySchema),
  baseline: signalAccuracyBaselineSchema,
});
export type SymbolAccuracyRankingResponse = z.infer<
  typeof symbolAccuracyRankingResponseSchema
>;

export function symbolAccuracyRanking(
  days: number,
  horizon: SignalAccuracyHorizon = 20,
): Promise<SymbolAccuracyRankingResponse> {
  const search = new URLSearchParams({
    days: String(days),
    horizon: String(horizon),
  });
  return apiRequest(
    `/api/v1/history/symbol-accuracy-ranking?${search.toString()}`,
    {
      method: 'GET',
      schema: symbolAccuracyRankingResponseSchema,
    },
  );
}
