// Watchlist group CRUD + per-symbol move. Each watchlist row belongs to
// at most one group; group_id=NULL means "未分類". Backend caps the user
// at 20 groups.

import { z } from 'zod';
import { apiRequest } from './client';
import { okResponseSchema } from './watchlistTags';

export const watchlistGroupSchema = z.object({
  id: z.number().int().nonnegative(),
  name: z.string(),
  position: z.number().int().nonnegative(),
  symbol_count: z.number().int().nonnegative(),
});
export type WatchlistGroup = z.infer<typeof watchlistGroupSchema>;

export const groupListResponseSchema = z.object({
  data: z.array(watchlistGroupSchema),
  total: z.number().int().nonnegative(),
});
export type GroupListResponse = z.infer<typeof groupListResponseSchema>;

export function listWatchlistGroups(): Promise<GroupListResponse> {
  return apiRequest('/api/v1/watchlist/groups', {
    method: 'GET',
    schema: groupListResponseSchema,
  });
}

export function createWatchlistGroup(input: { name: string }): Promise<WatchlistGroup> {
  return apiRequest('/api/v1/watchlist/groups', {
    method: 'POST',
    body: input,
    schema: watchlistGroupSchema,
  });
}

export function renameWatchlistGroup(
  groupId: number,
  newName: string,
): Promise<WatchlistGroup> {
  return apiRequest(`/api/v1/watchlist/groups/${groupId}`, {
    method: 'PATCH',
    body: { name: newName },
    schema: watchlistGroupSchema,
  });
}

export function deleteWatchlistGroup(
  groupId: number,
): Promise<z.infer<typeof okResponseSchema>> {
  return apiRequest(`/api/v1/watchlist/groups/${groupId}`, {
    method: 'DELETE',
    schema: okResponseSchema,
  });
}

// Reorder by sending the desired sequence of group IDs. Backend assigns
// positions 0..N-1 in this exact order — caller responsible for sending
// the full set of the user's groups (no partials).
export function reorderWatchlistGroups(
  orderedIds: number[],
): Promise<z.infer<typeof okResponseSchema>> {
  return apiRequest('/api/v1/watchlist/groups/reorder', {
    method: 'PATCH',
    body: { ordered_ids: orderedIds },
    schema: okResponseSchema,
  });
}

// Move a single watchlist symbol into a group, or set group_id=null to
// drop it back into "未分類".
export function moveSymbolToGroup(
  symbol: string,
  groupId: number | null,
): Promise<z.infer<typeof okResponseSchema>> {
  return apiRequest(`/api/v1/watchlist/${encodeURIComponent(symbol)}/group`, {
    method: 'PATCH',
    body: { group_id: groupId },
    schema: okResponseSchema,
  });
}
