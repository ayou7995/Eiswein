import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import {
  getMarketIndicatorSeries,
  type MarketIndicatorSeriesName,
  type MarketIndicatorSeriesResponse,
} from '../api/marketIndicatorSeries';

export function marketIndicatorSeriesQueryKey(
  name: MarketIndicatorSeriesName,
  days?: number,
): readonly unknown[] {
  // ``days`` is part of the cache key so that switching range selectors
  // doesn't return a stale-windowed payload from another range.
  return ['market-indicator-series', name, days ?? 'default'];
}

export interface UseMarketIndicatorSeriesOptions {
  enabled?: boolean;
  // Trailing-window length in trading days. Omit to use the route's
  // per-indicator default (e.g. yield_spread → 252, vix → 60).
  days?: number;
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
