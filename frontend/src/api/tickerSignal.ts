import { z } from 'zod';
import { apiRequest } from './client';
import { marketPostureSchema } from './marketPosture';
import { prosConsItemSchema } from './prosCons';

export const actionCategorySchema = z.enum([
  'strong_buy',
  'buy',
  'hold',
  'watch',
  'reduce',
  'exit',
]);
export type ActionCategoryCode = z.infer<typeof actionCategorySchema>;

export const timingModifierSchema = z.enum(['favorable', 'mixed', 'unfavorable']);
export type TimingModifierCode = z.infer<typeof timingModifierSchema>;

// Pydantic serializes Decimal as a quoted JSON string. Keep the wire shape
// honest (strings) and convert at consumption time with parseEntryPrice.
export const entryTiersSchema = z.object({
  aggressive: z.string().nullable(),
  ideal: z.string().nullable(),
  conservative: z.string().nullable(),
  split_suggestion: z.tuple([z.number(), z.number(), z.number()]),
});

export const tickerSignalResponseSchema = z.object({
  symbol: z.string(),
  date: z.string(),
  timezone: z.string(),
  action: actionCategorySchema,
  action_label: z.string(),
  direction_green_count: z.number().int().nonnegative(),
  direction_red_count: z.number().int().nonnegative(),
  timing_modifier: timingModifierSchema,
  timing_badge: z.string().nullable(),
  show_timing_modifier: z.boolean(),
  entry_tiers: entryTiersSchema,
  stop_loss: z.string().nullable(),
  market_posture_at_compute: marketPostureSchema,
  pros_cons: z.array(prosConsItemSchema),
  indicator_version: z.string(),
  computed_at: z.string(),
});

export type TickerSignalResponse = z.infer<typeof tickerSignalResponseSchema>;

// Single consumption point for Decimal-shaped prices. Returns null for
// null/empty/NaN inputs so the UI can collapse to a em-dash display.
export function parseDecimalString(value: string | null | undefined): number | null {
  if (value === null || value === undefined || value === '') return null;
  const parsed = Number.parseFloat(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function fetchTickerSignal(symbol: string): Promise<TickerSignalResponse> {
  return apiRequest(`/api/v1/ticker/${encodeURIComponent(symbol)}/signal`, {
    method: 'GET',
    schema: tickerSignalResponseSchema,
  });
}
