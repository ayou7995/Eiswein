import { z } from 'zod';
import { apiRequest } from './client';

// Generic job shape produced by the unified /api/v1/jobs/{id} endpoint.
// Both onboarding (per-symbol watchlist add) and revalidation (drift
// recompute) share this row — symbol is populated only for onboarding.
export const jobKindSchema = z.enum(['onboarding', 'revalidation']);
export type JobKind = z.infer<typeof jobKindSchema>;

export const jobStateSchema = z.enum([
  'pending',
  'running',
  'completed',
  'cancelled',
  'failed',
]);
export type JobState = z.infer<typeof jobStateSchema>;

export const jobSchema = z.object({
  id: z.number().int().nonnegative(),
  kind: jobKindSchema,
  symbol: z.string().nullable(),
  from_date: z.string(),
  to_date: z.string(),
  state: jobStateSchema,
  force: z.boolean(),
  processed_days: z.number().int().nonnegative(),
  total_days: z.number().int().nonnegative(),
  skipped_existing_days: z.number().int().nonnegative(),
  failed_days: z.number().int().nonnegative(),
  started_at: z.string().nullable(),
  finished_at: z.string().nullable(),
  error: z.string().nullable(),
  created_at: z.string(),
  created_by_user_id: z.number().int().nonnegative(),
  cancel_requested: z.boolean(),
});
export type Job = z.infer<typeof jobSchema>;

const TERMINAL_STATES: readonly JobState[] = ['completed', 'cancelled', 'failed'];

export function isTerminalJobState(state: JobState): boolean {
  return TERMINAL_STATES.includes(state);
}

export function getJob(jobId: number): Promise<Job> {
  return apiRequest(`/api/v1/jobs/${jobId}`, {
    method: 'GET',
    schema: jobSchema,
  });
}

export function cancelJob(jobId: number): Promise<Job> {
  return apiRequest(`/api/v1/jobs/${jobId}/cancel`, {
    method: 'POST',
    body: {},
    schema: jobSchema,
  });
}
