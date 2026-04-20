import { z } from 'zod';

// Shared wire shape for Pros/Cons items. Emitted by /market-posture and
// /ticker/{symbol}/signal. `detail` is passthrough metadata for the
// expand-on-tap UI; backend already filters to JSON primitives.
export const prosConsItemSchema = z.object({
  category: z.string(),
  tone: z.enum(['green', 'yellow', 'red', 'neutral']),
  short_label: z.string(),
  detail: z.record(z.unknown()),
  indicator_name: z.string(),
});

export type ProsConsItem = z.infer<typeof prosConsItemSchema>;
export type ProsConsTone = ProsConsItem['tone'];
