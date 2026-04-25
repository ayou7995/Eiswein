import { z } from 'zod';
import { apiRequest } from './client';

// Indicator drift summary. The dashboard banner keys off `has_drift`:
// when true it renders the "formulas changed — click to recompute" CTA.
// `running_revalidation_job_id` is populated while a revalidation job
// is in flight so the banner can switch to progress mode without a
// redundant POST.
export const driftStatusSchema = z.object({
  has_drift: z.boolean(),
  current_version: z.string(),
  stale_versions: z.array(z.string()),
  stale_row_count: z.number().int().nonnegative(),
  running_revalidation_job_id: z.number().int().nonnegative().nullable(),
});
export type DriftStatus = z.infer<typeof driftStatusSchema>;

export const revalidateResponseSchema = z.object({
  job_id: z.number().int().nonnegative(),
  state: z.string(),
});
export type RevalidateResponse = z.infer<typeof revalidateResponseSchema>;

export function getDriftStatus(): Promise<DriftStatus> {
  return apiRequest('/api/v1/indicators/drift', {
    method: 'GET',
    schema: driftStatusSchema,
  });
}

export function revalidateIndicators(): Promise<RevalidateResponse> {
  return apiRequest('/api/v1/indicators/revalidate', {
    method: 'POST',
    body: {},
    schema: revalidateResponseSchema,
  });
}
