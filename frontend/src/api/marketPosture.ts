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
  posture: marketPostureSchema,
  posture_label: z.string(),
  regime_green_count: z.number().int().nonnegative(),
  regime_red_count: z.number().int().nonnegative(),
  regime_yellow_count: z.number().int().nonnegative(),
  streak_days: z.number().int().nonnegative(),
  streak_badge: z.string().nullable(),
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
