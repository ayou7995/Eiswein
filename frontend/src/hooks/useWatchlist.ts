import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  addToWatchlist,
  getTickerStatus,
  listWatchlist,
  removeFromWatchlist,
  type WatchlistCreateResult,
  type WatchlistListResult,
} from '../api/watchlist';

const WATCHLIST_QUERY_KEY = ['watchlist'] as const;

export function useWatchlist(): ReturnType<typeof useQuery<WatchlistListResult>> {
  return useQuery({
    queryKey: WATCHLIST_QUERY_KEY,
    queryFn: listWatchlist,
    // Refetch when the tab regains focus so multi-device edits show up.
    refetchOnWindowFocus: true,
    staleTime: 30_000,
  });
}

export function useAddTicker(): ReturnType<
  typeof useMutation<WatchlistCreateResult, Error, string>
> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (symbol: string) => addToWatchlist(symbol),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: WATCHLIST_QUERY_KEY });
    },
  });
}

export function useRemoveTicker(): ReturnType<
  typeof useMutation<unknown, Error, string>
> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (symbol: string) => removeFromWatchlist(symbol),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: WATCHLIST_QUERY_KEY });
    },
  });
}

/**
 * Poll the lightweight `only_status=1` endpoint every 2 s while the
 * server-side backfill is still running. Stops polling automatically
 * once the status resolves.
 */
export function useTickerStatusPolling(
  symbol: string,
  enabled: boolean,
): ReturnType<typeof useQuery<Awaited<ReturnType<typeof getTickerStatus>>>> {
  return useQuery({
    queryKey: ['ticker-status', symbol],
    queryFn: () => getTickerStatus(symbol),
    enabled,
    refetchInterval: (q) => {
      const last = q.state.data;
      if (!last) return 2000;
      return last.dataStatus === 'pending' ? 2000 : false;
    },
  });
}
