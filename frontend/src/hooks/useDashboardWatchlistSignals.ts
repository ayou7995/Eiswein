import { useMemo } from 'react';
import { useQueries, type UseQueryResult } from '@tanstack/react-query';
import { fetchTickerSignal, type TickerSignalResponse } from '../api/tickerSignal';
import { EisweinApiError } from '../api/errors';
import { useWatchlist } from './useWatchlist';
import { tickerSignalQueryKey } from './useTickerSignal';
import type { WatchlistItem } from '../api/watchlist';

// Per-ticker status on the dashboard. Distinguishing `pending_signal` (404 from
// the backend — daily_update hasn't produced a snapshot yet) from `error`
// (network or schema failure) is important: the former is an expected state
// that renders a "分析運算中" placeholder, the latter surfaces as a red banner.
export type WatchlistSignalStatus =
  | 'loading'
  | 'ready'
  | 'pending_signal'
  | 'error';

export interface WatchlistSignalRow {
  item: WatchlistItem;
  status: WatchlistSignalStatus;
  signal: TickerSignalResponse | null;
  error: Error | null;
}

function deriveStatus(
  query: UseQueryResult<TickerSignalResponse>,
): WatchlistSignalStatus {
  if (query.isPending) return 'loading';
  if (query.isSuccess) return 'ready';
  if (query.error instanceof EisweinApiError && query.error.status === 404) {
    return 'pending_signal';
  }
  return 'error';
}

export interface DashboardWatchlistSignals {
  rows: readonly WatchlistSignalRow[];
  watchlistLoading: boolean;
  watchlistError: boolean;
  refetchWatchlist: () => Promise<unknown>;
}

export function useDashboardWatchlistSignals(): DashboardWatchlistSignals {
  const watchlist = useWatchlist();
  // Memoize so the array identity is stable across renders while the watchlist
  // payload hasn't changed — otherwise useQueries would recreate queries and
  // useMemo(rows) would invalidate on every parent render.
  const items = useMemo(
    () => watchlist.data?.data ?? [],
    [watchlist.data],
  );

  const queries = useQueries({
    queries: items.map((item) => ({
      queryKey: tickerSignalQueryKey(item.symbol),
      queryFn: () => fetchTickerSignal(item.symbol),
      // 404 is an expected outcome while daily_update runs. Retrying
      // only hides the "pending_signal" state behind an extra roundtrip.
      retry: false,
      refetchOnWindowFocus: false,
      staleTime: 5 * 60 * 1000,
    })),
  });

  const rows = useMemo<readonly WatchlistSignalRow[]>(() => {
    return items.map((item, index) => {
      const query = queries[index];
      if (!query) {
        return { item, status: 'loading', signal: null, error: null };
      }
      const status = deriveStatus(query);
      return {
        item,
        status,
        signal: status === 'ready' ? (query.data ?? null) : null,
        error: status === 'error' ? (query.error ?? null) : null,
      };
    });
  }, [items, queries]);

  return {
    rows,
    watchlistLoading: watchlist.isLoading,
    watchlistError: watchlist.isError,
    refetchWatchlist: () => watchlist.refetch(),
  };
}
