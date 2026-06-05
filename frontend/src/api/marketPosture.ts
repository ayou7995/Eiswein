import { z } from 'zod';
import { apiRequest } from './client';
import { prosConsItemSchema } from './prosCons';

// Backend's MarketPosture enum serializes with its English value string
// (`offensive` | `normal` | `defensive`). `posture_label` carries the
// Chinese display label so the UI never inlines a translation table.
export const marketPostureSchema = z.enum(['offensive', 'normal', 'defensive']);
export type MarketPostureCode = z.infer<typeof marketPostureSchema>;

export const marketPostureResponseSchema = z.object({
  date: z.string(),
  timezone: z.string(),
  // Mid-term posture (weeks horizon, 4 regime indicators).
  posture: marketPostureSchema,
  posture_label: z.string(),
  regime_green_count: z.number().int().nonnegative(),
  regime_red_count: z.number().int().nonnegative(),
  regime_yellow_count: z.number().int().nonnegative(),
  streak_days: z.number().int().nonnegative(),
  streak_badge: z.string().nullable(),
  // Short-term posture (days horizon, 2 fastest regime indicators).
  // v2 Phase 1 — paired with the mid-term posture in a dual badge so
  // operators can tell "structurally fine but today is panicky" apart
  // from "structurally weakening".
  //
  // The four fields are ``optional + default`` so a freshly-pulled
  // frontend gracefully degrades against a backend that has not been
  // rebuilt yet (which is exactly the failure mode we hit on the
  // first deploy of this commit: frontend ahead, backend behind →
  // Zod refused the response → "無法載入市場態勢"). Once backend
  // catches up the real values flow through normally.
  posture_short: marketPostureSchema.optional().default('normal'),
  posture_short_label: z.string().optional().default('正常'),
  regime_short_green_count: z.number().int().nonnegative().optional().default(0),
  regime_short_red_count: z.number().int().nonnegative().optional().default(0),
  pros_cons: z.array(prosConsItemSchema),
  indicator_version: z.string(),
  computed_at: z.string(),
});

export type MarketPostureResponse = z.infer<typeof marketPostureResponseSchema>;

export function fetchMarketPosture(): Promise<MarketPostureResponse> {
  return apiRequest('/api/v1/market-posture', {
    method: 'GET',
    schema: marketPostureResponseSchema,
  });
}
