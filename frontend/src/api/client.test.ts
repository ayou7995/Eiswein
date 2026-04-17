import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { z } from 'zod';
import { apiRequest, configureAuthClient, resetAuthClient } from './client';
import { EisweinApiError, SchemaValidationError } from './errors';

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

describe('apiRequest', () => {
  beforeEach(() => {
    resetAuthClient();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('parses a successful response against the Zod schema', async () => {
    const schema = z.object({ ok: z.literal(true), count: z.number() });
    const fetchMock = vi.fn(
      async (_url: string, _init?: RequestInit) => jsonResponse(200, { ok: true, count: 7 }),
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const result = await apiRequest('/api/v1/thing', { schema });
    expect(result).toEqual({ ok: true, count: 7 });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const firstCall = fetchMock.mock.calls[0];
    expect(firstCall).toBeDefined();
    const init = firstCall?.[1];
    expect(init).toBeDefined();
    expect(init?.credentials).toBe('include');
  });

  it('throws SchemaValidationError when the body does not match', async () => {
    const schema = z.object({ ok: z.literal(true), count: z.number() });
    const fetchMock = vi.fn(async () => jsonResponse(200, { ok: true, count: 'nope' }));
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    await expect(apiRequest('/api/v1/thing', { schema })).rejects.toBeInstanceOf(
      SchemaValidationError,
    );
  });

  it('parses the standardized error envelope on 4xx', async () => {
    const schema = z.object({ ok: z.literal(true) });
    const fetchMock = vi.fn(async () =>
      jsonResponse(401, {
        error: { code: 'invalid_password', message: '密碼錯誤', details: { attempts_remaining: 2 } },
      }),
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    await expect(
      apiRequest('/api/v1/login', { method: 'POST', body: {}, schema, skipAuthRefresh: true }),
    ).rejects.toMatchObject({
      name: 'EisweinApiError',
      code: 'invalid_password',
      status: 401,
      details: { attempts_remaining: 2 },
    });
  });

  it('coalesces concurrent 401s onto a single refresh call', async () => {
    const schema = z.object({ ok: z.literal(true) });

    let refreshCount = 0;
    const refresh = vi.fn(async () => {
      refreshCount += 1;
      await new Promise((r) => setTimeout(r, 10));
    });
    configureAuthClient({ refresh, onUnauthorized: () => undefined });

    const scripted: Array<() => Promise<Response>> = [
      async () => jsonResponse(401, { error: { code: 'expired', message: 'expired' } }),
      async () => jsonResponse(401, { error: { code: 'expired', message: 'expired' } }),
      async () => jsonResponse(401, { error: { code: 'expired', message: 'expired' } }),
      async () => jsonResponse(200, { ok: true }),
      async () => jsonResponse(200, { ok: true }),
      async () => jsonResponse(200, { ok: true }),
    ];
    const fetchMock = vi.fn(async () => {
      const next = scripted.shift();
      if (!next) throw new Error('unexpected extra fetch');
      return next();
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const results = await Promise.all([
      apiRequest('/api/v1/a', { schema }),
      apiRequest('/api/v1/b', { schema }),
      apiRequest('/api/v1/c', { schema }),
    ]);
    expect(results).toEqual([{ ok: true }, { ok: true }, { ok: true }]);
    expect(refreshCount).toBe(1);
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it('invokes the unauthorized handler when refresh itself fails', async () => {
    const schema = z.object({ ok: z.literal(true) });
    const refresh = vi.fn(async () => {
      throw new Error('refresh broken');
    });
    const onUnauthorized = vi.fn();
    configureAuthClient({ refresh, onUnauthorized });

    const fetchMock = vi.fn(async () =>
      jsonResponse(401, { error: { code: 'expired', message: 'expired' } }),
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    await expect(apiRequest('/api/v1/any', { schema })).rejects.toBeInstanceOf(EisweinApiError);
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
  });
});
