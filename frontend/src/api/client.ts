import type { ZodType, ZodTypeDef } from 'zod';
import { API_BASE_URL } from '../lib/constants';
import {
  EisweinApiError,
  NetworkError,
  SchemaValidationError,
  parseErrorEnvelope,
} from './errors';

export type HttpMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';

export interface RequestOptions<TResponse> {
  method?: HttpMethod;
  body?: unknown;
  // ZodType<Output, Def, Input> — using explicit Input = unknown so schemas
  // with input/output divergence (e.g. `.optional().default(…)` for
  // backward-compat fields) still satisfy this constraint when the caller
  // annotates the return type as the output shape.
  schema: ZodType<TResponse, ZodTypeDef, unknown>;
  signal?: AbortSignal;
  // Some endpoints (refresh, logout) must not themselves trigger a refresh on
  // 401 — otherwise a failed refresh would retry itself indefinitely.
  skipAuthRefresh?: boolean;
  headers?: Record<string, string>;
}

// Injection point for the refresh strategy. The auth context wires this up in
// Phase 0; tests override it to verify the single-flight dedupe.
export type RefreshFn = () => Promise<void>;
export type UnauthorizedHandler = () => void;

let refreshFn: RefreshFn | null = null;
let onUnauthorized: UnauthorizedHandler | null = null;
let inflightRefresh: Promise<void> | null = null;

export function configureAuthClient(options: {
  refresh: RefreshFn;
  onUnauthorized: UnauthorizedHandler;
}): void {
  refreshFn = options.refresh;
  onUnauthorized = options.onUnauthorized;
}

// Exposed for tests: reset module-level state between cases.
export function resetAuthClient(): void {
  refreshFn = null;
  onUnauthorized = null;
  inflightRefresh = null;
}

async function readJson(response: Response): Promise<unknown> {
  const contentType = response.headers.get('content-type') ?? '';
  if (response.status === 204 || !contentType.includes('application/json')) {
    return null;
  }
  try {
    return (await response.json()) as unknown;
  } catch {
    return null;
  }
}

async function dispatch<TResponse>(
  path: string,
  options: RequestOptions<TResponse>,
): Promise<{ status: number; body: unknown }> {
  const headers: Record<string, string> = {
    Accept: 'application/json',
    ...options.headers,
  };
  const method = options.method ?? 'GET';
  const init: RequestInit = {
    method,
    credentials: 'include',
    headers,
    ...(options.signal ? { signal: options.signal } : {}),
  };
  if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(options.body);
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, init);
  } catch (cause) {
    throw new NetworkError(cause instanceof Error ? cause.message : undefined);
  }
  const body = await readJson(response);
  return { status: response.status, body };
}

// Coalesces concurrent 401s onto a single refresh call (STAFF_REVIEW_DECISIONS.md
// B2). All callers wait on the same promise; success replays their request,
// failure bubbles a 401 up through the unauthorized handler.
// Exported so non-JSON transports (e.g. multipart import uploads) can reuse
// the same single-flight dedupe without re-implementing it.
export async function ensureRefresh(): Promise<void> {
  if (!refreshFn) {
    throw new EisweinApiError(401, 'unauthenticated', '尚未登入');
  }
  if (!inflightRefresh) {
    inflightRefresh = refreshFn()
      .catch((err: unknown) => {
        onUnauthorized?.();
        throw err;
      })
      .finally(() => {
        inflightRefresh = null;
      });
  }
  await inflightRefresh;
}

export async function apiRequest<TResponse>(
  path: string,
  options: RequestOptions<TResponse>,
): Promise<TResponse> {
  let first = await dispatch<TResponse>(path, options);

  if (first.status === 401 && !options.skipAuthRefresh) {
    try {
      await ensureRefresh();
    } catch {
      throw parseErrorEnvelope(first.status, first.body);
    }
    first = await dispatch<TResponse>(path, options);
  }

  if (first.status >= 400) {
    throw parseErrorEnvelope(first.status, first.body);
  }

  const parsed = options.schema.safeParse(first.body);
  if (!parsed.success) {
    throw new SchemaValidationError(
      `回應資料格式錯誤 (${path})`,
      parsed.error.issues,
    );
  }
  return parsed.data;
}
