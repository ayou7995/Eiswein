import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import {
  getMarketIndicatorSeries,
  type MarketIndicatorSeriesName,
  type MarketIndicatorSeriesResponse,
} from '../api/marketIndicatorSeries';

export function marketIndicatorSeriesQueryKey(name: MarketIndicatorSeriesName): readonly unknown[] {
  return ['market-indicator-series', name];
}

export interface UseMarketIndicatorSeriesOptions {
  enabled?: boolean;
}

export function useMarketIndicatorSeries(
  name: MarketIndicatorSeriesName,
  options: UseMarketIndicatorSeriesOptions = {},
): UseQueryResult<MarketIndicatorSeriesResponse> {
  const { enabled = true } = options;
  return useQuery({
    queryKey: marketIndicatorSeriesQueryKey(name),
    queryFn: () => getMarketIndicatorSeries(name),
    enabled,
    refetchOnWindowFocus: false,
    staleTime: 60 * 1000,
    retry: 0,
  });
}
