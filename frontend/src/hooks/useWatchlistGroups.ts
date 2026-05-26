import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  createWatchlistGroup,
  deleteWatchlistGroup,
  listWatchlistGroups,
  moveSymbolToGroup,
  renameWatchlistGroup,
  reorderWatchlistGroups,
  type GroupListResponse,
  type WatchlistGroup,
} from '../api/watchlistGroups';

const GROUPS_KEY = ['watchlist', 'groups'] as const;
const WATCHLIST_KEY = ['watchlist'] as const;

function invalidateGroupCaches(qc: ReturnType<typeof useQueryClient>): void {
  void qc.invalidateQueries({ queryKey: GROUPS_KEY });
  // group_id is denormalized into the watchlist list response — keep both
  // caches in sync on every group mutation.
  void qc.invalidateQueries({ queryKey: WATCHLIST_KEY });
}

export function useWatchlistGroups(): ReturnType<typeof useQuery<GroupListResponse>> {
  return useQuery({
    queryKey: GROUPS_KEY,
    queryFn: listWatchlistGroups,
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });
}

export function useCreateWatchlistGroup(): ReturnType<
  typeof useMutation<WatchlistGroup, Error, { name: string }>
> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input) => createWatchlistGroup(input),
    onSuccess: () => invalidateGroupCaches(qc),
  });
}

export function useRenameWatchlistGroup(): ReturnType<
  typeof useMutation<WatchlistGroup, Error, { groupId: number; name: string }>
> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ groupId, name }) => renameWatchlistGroup(groupId, name),
    onSuccess: () => invalidateGroupCaches(qc),
  });
}

export function useDeleteWatchlistGroup(): ReturnType<
  typeof useMutation<unknown, Error, number>
> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (groupId) => deleteWatchlistGroup(groupId),
    onSuccess: () => invalidateGroupCaches(qc),
  });
}

export function useReorderWatchlistGroups(): ReturnType<
  typeof useMutation<unknown, Error, number[]>
> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (orderedIds) => reorderWatchlistGroups(orderedIds),
    onSuccess: () => invalidateGroupCaches(qc),
  });
}

export function useMoveSymbolToGroup(): ReturnType<
  typeof useMutation<unknown, Error, { symbol: string; groupId: number | null }>
> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ symbol, groupId }) => moveSymbolToGroup(symbol, groupId),
    onSuccess: () => invalidateGroupCaches(qc),
  });
}
