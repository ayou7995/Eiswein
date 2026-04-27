import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import {
  getIndicatorSeries,
  type IndicatorSeriesName,
  type IndicatorSeriesResponse,
} from '../api/tickerIndicatorSeries';

export function indicatorSeriesQueryKey(
  symbol: string,
  name: IndicatorSeriesName,
  days?: number,
): readonly unknown[] {
  // ``days`` is part of the cache key so range switching doesn't return
  // a stale-windowed payload from another range.
  return ['indicator-series', symbol, name, days ?? 'default'];
}

export interface UseIndicatorSeriesOptions {
  enabled?: boolean;
  // Trailing-window length in trading days. Omit to use the route's
  // legacy 60-day default.
  days?: number;
}

export function useIndicatorSeries(
  symbol: string,
  name: IndicatorSeriesName,
  options: UseIndicatorSeriesOptions = {},
): UseQueryResult<IndicatorSeriesResponse> {
  const { enabled = true, days } = options;
  return useQuery({
    queryKey: indicatorSeriesQueryKey(symbol, name, days),
    queryFn: () => getIndicatorSeries(symbol, name, days),
    enabled: enabled && symbol.length > 0,
    refetchOnWindowFocus: false,
    staleTime: 60 * 1000,
    retry: 0,
  });
}
