import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  addToPosition,
  closePosition,
  createPosition,
  getPosition,
  listPositions,
  reducePosition,
} from './positions';
import { EisweinApiError, SchemaValidationError } from './errors';
import { resetAuthClient } from './client';

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

function installFetch(
  handler: (url: string, init?: RequestInit) => { status: number; body: unknown },
): () => void {
  const original = globalThis.fetch;
  const mock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.toString();
    const { status, body } = handler(url, init);
    return jsonResponse(status, body);
  });
  globalThis.fetch = mock as unknown as typeof fetch;
  return () => {
    globalThis.fetch = original;
  };
}

const SAMPLE_POSITION = {
  id: 7,
  symbol: 'AAPL',
  shares: '10.000000',
  avg_cost: '180.000000',
  opened_at: '2026-04-10T15:30:00Z',
  closed_at: null,
  notes: null,
  current_price: '190.000000',
  unrealized_pnl: '100.000000',
};

const SAMPLE_TRADE = {
  id: 101,
  position_id: 7,
  symbol: 'AAPL',
  side: 'buy' as const,
  shares: '10.000000',
  price: '180.000000',
  executed_at: '2026-04-10T15:30:00Z',
  realized_pnl: null,
  note: null,
  created_at: '2026-04-10T15:30:01Z',
};

describe('positions API client', () => {
  beforeEach(() => {
    resetAuthClient();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('listPositions parses the list envelope', async () => {
    const restore = installFetch(() => ({
      status: 200,
      body: { data: [SAMPLE_POSITION], total: 1, has_more: false },
    }));
    try {
      const result = await listPositions(false);
      expect(result.total).toBe(1);
      expect(result.data[0]?.symbol).toBe('AAPL');
      expect(result.data[0]?.shares).toBe('10.000000');
    } finally {
      restore();
    }
  });

  it('listPositions sends include_closed flag', async () => {
    const handler = vi.fn((url: string) => ({
      status: 200,
      body: { data: [], total: 0, has_more: false },
      _url: url,
    }));
    const restore = installFetch(handler);
    try {
      await listPositions(true);
      expect(handler).toHaveBeenCalled();
      const firstCall = handler.mock.calls[0];
      expect(firstCall?.[0]).toContain('include_closed=1');
    } finally {
      restore();
    }
  });

  it('createPosition unwraps the envelope', async () => {
    const restore = installFetch(() => ({
      status: 201,
      body: { data: SAMPLE_POSITION },
    }));
    try {
      const result = await createPosition({
        symbol: 'AAPL',
        shares: '10',
        price: '180',
        executed_at: '2026-04-10T15:30:00Z',
      });
      expect(result.id).toBe(7);
      expect(result.symbol).toBe('AAPL');
    } finally {
      restore();
    }
  });

  it('getPosition includes recent_trades', async () => {
    const restore = installFetch(() => ({
      status: 200,
      body: { data: { ...SAMPLE_POSITION, recent_trades: [SAMPLE_TRADE] } },
    }));
    try {
      const detail = await getPosition(7);
      expect(detail.recent_trades).toHaveLength(1);
      expect(detail.recent_trades[0]?.side).toBe('buy');
    } finally {
      restore();
    }
  });

  it('addToPosition + reducePosition unwrap the envelope', async () => {
    const restore = installFetch(() => ({
      status: 200,
      body: { data: SAMPLE_POSITION },
    }));
    try {
      const afterAdd = await addToPosition(7, {
        shares: '5',
        price: '185',
        executed_at: '2026-04-11T15:30:00Z',
      });
      expect(afterAdd.symbol).toBe('AAPL');
      const afterReduce = await reducePosition(7, {
        shares: '2',
        price: '200',
        executed_at: '2026-04-12T15:30:00Z',
      });
      expect(afterReduce.symbol).toBe('AAPL');
    } finally {
      restore();
    }
  });

  it('closePosition parses OK envelope', async () => {
    const restore = installFetch(() => ({ status: 200, body: { ok: true } }));
    try {
      const ok = await closePosition(7);
      expect(ok.ok).toBe(true);
    } finally {
      restore();
    }
  });

  it('surfaces EisweinApiError when the server returns an error envelope', async () => {
    const restore = installFetch(() => ({
      status: 409,
      body: {
        error: {
          code: 'position_conflict',
          message: '股數尚未歸零',
          details: { reason: 'has_remaining_shares' },
        },
      },
    }));
    try {
      await expect(closePosition(7)).rejects.toBeInstanceOf(EisweinApiError);
    } finally {
      restore();
    }
  });

  it('surfaces SchemaValidationError when shape is unexpected', async () => {
    const restore = installFetch(() => ({
      status: 200,
      body: { nope: true },
    }));
    try {
      await expect(listPositions(false)).rejects.toBeInstanceOf(SchemaValidationError);
    } finally {
      restore();
    }
  });
});
