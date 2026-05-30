import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import {
  getIndicatorSeries,
  type IndicatorSeriesName,
  type IndicatorSeriesResponse,
} from '../api/tickerIndicatorSeries';

export function indicatorSeriesQueryKey(
  symbol: string,
  name: IndicatorSeriesName,
  daysOrAll?: number | 'all',
): readonly unknown[] {
  // The window selector is part of the cache key so range switching
  // doesn't return a stale-windowed payload from another range.
  return ['indicator-series', symbol, name, daysOrAll ?? 'default'];
}

export interface UseIndicatorSeriesOptions {
  enabled?: boolean;
  // Trailing-window length in trading days, or the string 'all' to ask
  // the server for the full backfilled history. Omit to use the route's
  // legacy 60-day default.
  days?: number | 'all';
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
