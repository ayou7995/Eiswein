import { z } from 'zod';
import { apiRequest } from './client';

export const passwordChangeResponseSchema = z.object({
  ok: z.literal(true),
});

export async function changePassword(input: {
  currentPassword: string;
  newPassword: string;
}): Promise<void> {
  await apiRequest('/api/v1/settings/password', {
    method: 'POST',
    body: {
      current_password: input.currentPassword,
      new_password: input.newPassword,
    },
    schema: passwordChangeResponseSchema,
  });
}

// Event-type strings come from backend's audit_repository constants
// (login_success, password_changed, position_opened, ...). The values
// are arbitrary identifiers — keep the schema permissive so new events
// don't break the UI; we map to Chinese labels in the page layer.
export const auditEntrySchema = z.object({
  id: z.number().int().nonnegative(),
  timestamp: z.string(),
  event_type: z.string(),
  ip: z.string().nullable(),
  details: z.record(z.unknown()),
});
export type AuditEntry = z.infer<typeof auditEntrySchema>;

export const auditLogResponseSchema = z.object({
  data: z.array(auditEntrySchema),
  total: z.number().int().nonnegative(),
  has_more: z.boolean(),
});
export type AuditLogResponse = z.infer<typeof auditLogResponseSchema>;

export function listAuditLog(limit: number): Promise<AuditLogResponse> {
  const search = new URLSearchParams({ limit: String(limit) });
  return apiRequest(`/api/v1/settings/audit-log?${search.toString()}`, {
    method: 'GET',
    schema: auditLogResponseSchema,
  });
}

export const systemInfoResponseSchema = z.object({
  db_size_bytes: z.number().int().nonnegative().nullable(),
  last_daily_update_at: z.string().nullable(),
  last_backup_at: z.string().nullable(),
  watchlist_count: z.number().int().nonnegative(),
  positions_count: z.number().int().nonnegative(),
  trade_count: z.number().int().nonnegative(),
  user_count: z.number().int().nonnegative().nullable(),
});
export type SystemInfoResponse = z.infer<typeof systemInfoResponseSchema>;

export function systemInfo(): Promise<SystemInfoResponse> {
  return apiRequest('/api/v1/settings/system-info', {
    method: 'GET',
    schema: systemInfoResponseSchema,
  });
}

export const dataRefreshResponseSchema = z.object({
  ok: z.literal(true),
  job_id: z.string(),
  started_at: z.string(),
  market_open: z.boolean(),
  gaps_filled_rows: z.number().int().nonnegative(),
  gaps_filled_symbols: z.number().int().nonnegative(),
});
export type DataRefreshResponse = z.infer<typeof dataRefreshResponseSchema>;

export function triggerDataRefresh(): Promise<DataRefreshResponse> {
  return apiRequest('/api/v1/settings/data-refresh', {
    method: 'POST',
    // Backend ignores body; empty object keeps the JSON content-type consistent.
    body: {},
    schema: dataRefreshResponseSchema,
  });
}
