import { z } from 'zod';
import { API_BASE_URL } from '../lib/constants';
import { apiRequest, ensureRefresh } from './client';
import { NetworkError, parseErrorEnvelope } from './errors';

// --- Schemas ---------------------------------------------------------------

export const schwabAccountSchema = z.object({
  display_id: z.string(),
  nickname: z.string().nullable(),
});
export type SchwabAccount = z.infer<typeof schwabAccountSchema>;

// The backend returns a half-inhabited object when disconnected (just
// `connected: false`); all the other fields only appear on connected rows.
// We model that with optional fields rather than a discriminated union so the
// UI can read `status.accounts` directly without a type narrow on each access.
export const schwabStatusSchema = z.object({
  connected: z.boolean(),
  accounts: z.array(schwabAccountSchema).optional(),
  mkt_data_permission: z.string().nullable().optional(),
  last_test_at: z.string().nullable().optional(),
  last_test_status: z.enum(['success', 'failed']).nullable().optional(),
  last_test_latency_ms: z.number().int().nullable().optional(),
  last_refreshed_at: z.string().nullable().optional(),
});
export type SchwabStatus = z.infer<typeof schwabStatusSchema>;

export const schwabTestErrorSchema = z.object({
  code: z.string(),
  message: z.string(),
});

export const schwabTestResultSchema = z.object({
  success: z.boolean(),
  latency_ms: z.number().int().nullable(),
  account_count: z.number().int().nullable(),
  mkt_data_permission: z.string().nullable(),
  error: schwabTestErrorSchema.nullable(),
});
export type SchwabTestResult = z.infer<typeof schwabTestResultSchema>;

// --- Fetchers --------------------------------------------------------------

export function getSchwabStatus(): Promise<SchwabStatus> {
  return apiRequest('/api/v1/broker/schwab/status', {
    method: 'GET',
    schema: schwabStatusSchema,
  });
}

export function testSchwabConnection(): Promise<SchwabTestResult> {
  return apiRequest('/api/v1/broker/schwab/test', {
    method: 'POST',
    body: {},
    schema: schwabTestResultSchema,
  });
}

// Disconnect returns 204 No Content. `apiRequest` expects a JSON body that
// validates against its schema — an empty body would always fail parsing. So
// we dispatch directly here, reusing `ensureRefresh` for the 401 single-flight
// behavior to keep auth semantics identical to every other call.
async function requestNoContent(path: string, method: 'POST'): Promise<void> {
  const init: RequestInit = {
    method,
    credentials: 'include',
    headers: { Accept: 'application/json' },
  };
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, init);
  } catch (cause) {
    throw new NetworkError(cause instanceof Error ? cause.message : undefined);
  }
  if (response.status === 401) {
    await ensureRefresh();
    try {
      response = await fetch(`${API_BASE_URL}${path}`, init);
    } catch (cause) {
      throw new NetworkError(cause instanceof Error ? cause.message : undefined);
    }
  }
  if (response.status === 204) return;
  // Non-204 after auth refresh is either an error envelope or an unexpected
  // success body — parse the envelope for the former and raise otherwise.
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    // no-op; body stays null and parseErrorEnvelope yields a generic message
  }
  throw parseErrorEnvelope(response.status, body);
}

export function disconnectSchwab(): Promise<void> {
  return requestNoContent('/api/v1/broker/schwab/disconnect', 'POST');
}

// Exported as a named function (not inlined) so tests can mock it and the
// component under test can be asserted without a real `window.location` nav.
//
// The OAuth `state` nonce is stored in an HttpOnly cookie bound to whatever
// origin serves `/schwab/start`. After the user completes the Schwab flow,
// Schwab redirects the browser to `SCHWAB_REDIRECT_URI` — which points at
// the backend's absolute origin (e.g. `https://127.0.0.1:8000` locally).
// If `/schwab/start` ran through the Vite proxy, the cookie would live on
// `localhost:5173` and the callback on `127.0.0.1:8000` would see no cookie
// → nonce mismatch → silent error redirect. So we force a top-level
// navigation to the backend origin here. This is a nav (not a fetch), so
// CORS doesn't apply.
//
// `VITE_BROKER_ORIGIN` should be set to the backend's externally-visible
// origin (matching `SCHWAB_REDIRECT_URI`). In production behind a single
// Cloudflare Tunnel hostname, leave it empty — relative path works.
export function startSchwabOAuth(): void {
  const brokerOrigin = (import.meta.env.VITE_BROKER_ORIGIN ?? '').replace(/\/$/, '');
  const base = brokerOrigin || API_BASE_URL;
  window.location.href = `${base}/api/v1/broker/schwab/start`;
}
