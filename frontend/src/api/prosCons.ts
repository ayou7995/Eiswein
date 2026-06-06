import { z } from 'zod';

// Shared wire shape for Pros/Cons items. Emitted by /market-posture and
// /ticker/{symbol}/signal. `detail` is passthrough metadata for the
// expand-on-tap UI; backend already filters to JSON primitives.
// Backend emits `tone` as pros/cons semantic role (pro/con/neutral),
// NOT the signal-color scheme. `category` carries the indicator class
// (direction/timing/macro). Keep the shapes aligned — the UI maps
// pro→🟢, con→🔴, neutral→⚪.
export const prosConsItemSchema = z.object({
  category: z.string(),
  tone: z.enum(['pro', 'con', 'neutral']),
  short_label: z.string(),
  detail: z.record(z.unknown()),
  indicator_name: z.string(),
  timeframe: z.enum(['short', 'mid', 'long']),
  // Actual underlying-data date (YYYY-MM-DD). When < the snapshot's
  // date the indicator was computed from older bars (FRED publication
  // lag, yfinance partial fetch, etc.) — UI surfaces this as a
  // 「資料截至 X」 pill so today's number isn't mistaken for today's data.
  // Optional + nullable: legacy DailySignal rows have no value.
  data_as_of: z.string().nullable().optional(),
});

export type ProsConsItem = z.infer<typeof prosConsItemSchema>;
export type ProsConsTone = ProsConsItem['tone'];
