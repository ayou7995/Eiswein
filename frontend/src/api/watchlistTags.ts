// Watchlist tag CRUD + attach/detach. The grouped sidebar consumes the
// list + popular endpoints; per-row tag chips are sent via the symbol
// attach/detach endpoints. Backend caps the user at 30 tags.

import { z } from 'zod';
import { apiRequest } from './client';

export const watchlistTagSchema = z.object({
  id: z.number().int().nonnegative(),
  name: z.string(),
  color: z.string().regex(/^#[0-9A-Fa-f]{6}$/),
});
export type WatchlistTag = z.infer<typeof watchlistTagSchema>;

export const tagListResponseSchema = z.object({
  data: z.array(watchlistTagSchema),
  total: z.number().int().nonnegative(),
  // Up to 8 most-attached tags — used as "+ AI / + 高信念 / ..." suggestion
  // chips inside the EditTagsCard so the operator can one-click pick.
  popular: z.array(watchlistTagSchema),
});
export type TagListResponse = z.infer<typeof tagListResponseSchema>;

export const okResponseSchema = z.object({ ok: z.literal(true) });

export function listWatchlistTags(): Promise<TagListResponse> {
  return apiRequest('/api/v1/watchlist/tags', {
    method: 'GET',
    schema: tagListResponseSchema,
  });
}

export function createWatchlistTag(input: {
  name: string;
  color: string;
}): Promise<WatchlistTag> {
  return apiRequest('/api/v1/watchlist/tags', {
    method: 'POST',
    body: input,
    schema: watchlistTagSchema,
  });
}

export function updateWatchlistTag(
  tagId: number,
  patch: { name?: string | undefined; color?: string | undefined },
): Promise<WatchlistTag> {
  // Strip undefined keys so the backend's Pydantic partial schema doesn't
  // see explicit nulls (we only want to PATCH fields the caller set).
  const body: Record<string, string> = {};
  if (patch.name !== undefined) body.name = patch.name;
  if (patch.color !== undefined) body.color = patch.color;
  return apiRequest(`/api/v1/watchlist/tags/${tagId}`, {
    method: 'PATCH',
    body,
    schema: watchlistTagSchema,
  });
}

export function deleteWatchlistTag(tagId: number): Promise<z.infer<typeof okResponseSchema>> {
  return apiRequest(`/api/v1/watchlist/tags/${tagId}`, {
    method: 'DELETE',
    schema: okResponseSchema,
  });
}

export function attachTagToSymbol(
  symbol: string,
  tagId: number,
): Promise<z.infer<typeof okResponseSchema>> {
  return apiRequest(
    `/api/v1/watchlist/${encodeURIComponent(symbol)}/tags/${tagId}`,
    {
      method: 'POST',
      schema: okResponseSchema,
    },
  );
}

export function detachTagFromSymbol(
  symbol: string,
  tagId: number,
): Promise<z.infer<typeof okResponseSchema>> {
  return apiRequest(
    `/api/v1/watchlist/${encodeURIComponent(symbol)}/tags/${tagId}`,
    {
      method: 'DELETE',
      schema: okResponseSchema,
    },
  );
}
