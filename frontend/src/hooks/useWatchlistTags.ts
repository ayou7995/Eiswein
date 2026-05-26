import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  attachTagToSymbol,
  createWatchlistTag,
  deleteWatchlistTag,
  detachTagFromSymbol,
  listWatchlistTags,
  updateWatchlistTag,
  type TagListResponse,
  type WatchlistTag,
} from '../api/watchlistTags';

const TAGS_KEY = ['watchlist', 'tags'] as const;
const WATCHLIST_KEY = ['watchlist'] as const;

function invalidateTagCaches(qc: ReturnType<typeof useQueryClient>): void {
  void qc.invalidateQueries({ queryKey: TAGS_KEY });
  // Watchlist response embeds per-row tags[]; invalidate so the
  // sidebar shows the change immediately.
  void qc.invalidateQueries({ queryKey: WATCHLIST_KEY });
}

export function useWatchlistTags(): ReturnType<typeof useQuery<TagListResponse>> {
  return useQuery({
    queryKey: TAGS_KEY,
    queryFn: listWatchlistTags,
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });
}

export function useCreateWatchlistTag(): ReturnType<
  typeof useMutation<WatchlistTag, Error, { name: string; color: string }>
> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input) => createWatchlistTag(input),
    onSuccess: () => invalidateTagCaches(qc),
  });
}

export function useUpdateWatchlistTag(): ReturnType<
  typeof useMutation<
    WatchlistTag,
    Error,
    { tagId: number; name?: string; color?: string }
  >
> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ tagId, name, color }) => updateWatchlistTag(tagId, { name, color }),
    onSuccess: () => invalidateTagCaches(qc),
  });
}

export function useDeleteWatchlistTag(): ReturnType<
  typeof useMutation<unknown, Error, number>
> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (tagId) => deleteWatchlistTag(tagId),
    onSuccess: () => invalidateTagCaches(qc),
  });
}

export function useAttachTag(): ReturnType<
  typeof useMutation<unknown, Error, { symbol: string; tagId: number }>
> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ symbol, tagId }) => attachTagToSymbol(symbol, tagId),
    onSuccess: () => invalidateTagCaches(qc),
  });
}

export function useDetachTag(): ReturnType<
  typeof useMutation<unknown, Error, { symbol: string; tagId: number }>
> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ symbol, tagId }) => detachTagFromSymbol(symbol, tagId),
    onSuccess: () => invalidateTagCaches(qc),
  });
}
