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
});

export type ProsConsItem = z.infer<typeof prosConsItemSchema>;
export type ProsConsTone = ProsConsItem['tone'];
