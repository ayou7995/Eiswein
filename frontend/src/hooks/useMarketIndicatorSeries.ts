import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import {
  getMarketIndicatorSeries,
  type MarketIndicatorSeriesName,
  type MarketIndicatorSeriesResponse,
} from '../api/marketIndicatorSeries';

export function marketIndicatorSeriesQueryKey(
  name: MarketIndicatorSeriesName,
  daysOrAll?: number | 'all',
): readonly unknown[] {
  // The window selector is part of the cache key so that flipping ranges
  // doesn't return a stale-windowed payload from another range.
  return ['market-indicator-series', name, daysOrAll ?? 'default'];
}

export interface UseMarketIndicatorSeriesOptions {
  enabled?: boolean;
  // Trailing-window length in trading days, or the string 'all' to ask
  // the server for the full backfilled history. Omit to use the route's
  // per-indicator default (e.g. yield_spread → 252, vix → 60).
  days?: number | 'all';
}

export function useMarketIndicatorSeries(
  name: MarketIndicatorSeriesName,
  options: UseMarketIndicatorSeriesOptions = {},
): UseQueryResult<MarketIndicatorSeriesResponse> {
  const { enabled = true, days } = options;
  return useQuery({
    queryKey: marketIndicatorSeriesQueryKey(name, days),
    queryFn: () => getMarketIndicatorSeries(name, days),
    enabled,
    refetchOnWindowFocus: false,
    staleTime: 60 * 1000,
    retry: 0,
  });
}
