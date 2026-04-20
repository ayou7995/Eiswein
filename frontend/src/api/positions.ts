import { z } from 'zod';
import { apiRequest } from './client';

// Decimal fields on the wire are ALWAYS strings (backend quantizes to
// 6dp via str(Decimal.quantize(...))). Keep them as strings through the
// schema boundary and parse at the display layer with parseDecimalString
// from ./tickerSignal — float64 loses precision on large share counts.

export const tradeSideSchema = z.enum(['buy', 'sell']);
export type TradeSide = z.infer<typeof tradeSideSchema>;

export const tradeResponseSchema = z.object({
  id: z.number().int().nonnegative(),
  position_id: z.number().int().nullable(),
  symbol: z.string(),
  side: tradeSideSchema,
  shares: z.string(),
  price: z.string(),
  executed_at: z.string(),
  realized_pnl: z.string().nullable(),
  note: z.string().nullable(),
  created_at: z.string(),
});
export type TradeResponse = z.infer<typeof tradeResponseSchema>;

export const positionResponseSchema = z.object({
  id: z.number().int().nonnegative(),
  symbol: z.string(),
  shares: z.string(),
  avg_cost: z.string(),
  opened_at: z.string(),
  closed_at: z.string().nullable(),
  notes: z.string().nullable(),
  current_price: z.string().nullable(),
  unrealized_pnl: z.string().nullable(),
});
export type PositionResponse = z.infer<typeof positionResponseSchema>;

export const positionWithTradesSchema = positionResponseSchema.extend({
  recent_trades: z.array(tradeResponseSchema),
});
export type PositionWithTrades = z.infer<typeof positionWithTradesSchema>;

export const positionsListResponseSchema = z.object({
  data: z.array(positionResponseSchema),
  total: z.number().int().nonnegative(),
  has_more: z.boolean(),
});
export type PositionsListResponse = z.infer<typeof positionsListResponseSchema>;

export const positionEnvelopeSchema = z.object({
  data: positionResponseSchema,
});

export const positionDetailEnvelopeSchema = z.object({
  data: positionWithTradesSchema,
});

export const okResponseSchema = z.object({ ok: z.literal(true) });

export interface OpenPositionInput {
  symbol: string;
  shares: string;
  price: string;
  executed_at: string;
  note?: string | null;
}

export interface AdjustPositionInput {
  shares: string;
  price: string;
  executed_at: string;
  note?: string | null;
}

function adjustBody(input: AdjustPositionInput): Record<string, unknown> {
  const body: Record<string, unknown> = {
    shares: input.shares,
    price: input.price,
    executed_at: input.executed_at,
  };
  if (input.note != null && input.note !== '') {
    body['note'] = input.note;
  }
  return body;
}

export async function listPositions(
  includeClosed: boolean,
): Promise<PositionsListResponse> {
  const search = new URLSearchParams({ include_closed: includeClosed ? '1' : '0' });
  return apiRequest(`/api/v1/positions?${search.toString()}`, {
    method: 'GET',
    schema: positionsListResponseSchema,
  });
}

export async function createPosition(
  input: OpenPositionInput,
): Promise<PositionResponse> {
  const body: Record<string, unknown> = {
    symbol: input.symbol,
    shares: input.shares,
    price: input.price,
    executed_at: input.executed_at,
  };
  if (input.note != null && input.note !== '') {
    body['note'] = input.note;
  }
  const raw = await apiRequest('/api/v1/positions', {
    method: 'POST',
    body,
    schema: positionEnvelopeSchema,
  });
  return raw.data;
}

export async function getPosition(id: number): Promise<PositionWithTrades> {
  const raw = await apiRequest(`/api/v1/positions/${id}`, {
    method: 'GET',
    schema: positionDetailEnvelopeSchema,
  });
  return raw.data;
}

export async function addToPosition(
  id: number,
  input: AdjustPositionInput,
): Promise<PositionResponse> {
  const raw = await apiRequest(`/api/v1/positions/${id}/add`, {
    method: 'POST',
    body: adjustBody(input),
    schema: positionEnvelopeSchema,
  });
  return raw.data;
}

export async function reducePosition(
  id: number,
  input: AdjustPositionInput,
): Promise<PositionResponse> {
  const raw = await apiRequest(`/api/v1/positions/${id}/reduce`, {
    method: 'POST',
    body: adjustBody(input),
    schema: positionEnvelopeSchema,
  });
  return raw.data;
}

export async function closePosition(
  id: number,
): Promise<z.infer<typeof okResponseSchema>> {
  return apiRequest(`/api/v1/positions/${id}`, {
    method: 'DELETE',
    schema: okResponseSchema,
  });
}
