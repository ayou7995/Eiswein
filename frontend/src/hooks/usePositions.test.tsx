import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import {
  positionQueryKey,
  positionsQueryKey,
  useCreatePosition,
} from './usePositions';
import { resetAuthClient } from '../api/client';

function installFetch(
  handler: (url: string) => { status: number; body: unknown },
): () => void {
  const original = globalThis.fetch;
  const mock = vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === 'string' ? input : input.toString();
    const { status, body } = handler(url);
    return new Response(JSON.stringify(body), {
      status,
      headers: { 'content-type': 'application/json' },
    });
  });
  globalThis.fetch = mock as unknown as typeof fetch;
  return () => {
    globalThis.fetch = original;
  };
}

function makeWrapper(client: QueryClient): (props: { children: ReactNode }) => JSX.Element {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

describe('useCreatePosition', () => {
  beforeEach(() => {
    resetAuthClient();
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('invalidates positions cache on success', async () => {
    const restore = installFetch((url) => {
      if (url.endsWith('/api/v1/positions')) {
        return {
          status: 201,
          body: {
            data: {
              id: 1,
              symbol: 'AAPL',
              shares: '10.000000',
              avg_cost: '180.000000',
              opened_at: '2026-04-10T15:30:00Z',
              closed_at: null,
              notes: null,
              current_price: null,
              unrealized_pnl: null,
            },
          },
        };
      }
      throw new Error(`unexpected ${url}`);
    });
    try {
      const client = new QueryClient({
        defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
      });
      // Seed caches so we can prove they were invalidated.
      client.setQueryData(positionsQueryKey(false), {
        data: [],
        total: 0,
        has_more: false,
      });
      client.setQueryData(positionQueryKey(42), null);
      const invalidateSpy = vi.spyOn(client, 'invalidateQueries');

      const { result } = renderHook(() => useCreatePosition(), {
        wrapper: makeWrapper(client),
      });

      await result.current.mutateAsync({
        symbol: 'AAPL',
        shares: '10',
        price: '180',
        executed_at: '2026-04-10T15:30:00Z',
      });

      await waitFor(() => {
        expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['positions'] });
      });
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['position'] });
    } finally {
      restore();
    }
  });
});
