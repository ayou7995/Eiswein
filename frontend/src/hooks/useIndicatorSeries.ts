import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import {
  getIndicatorSeries,
  type IndicatorSeriesName,
  type IndicatorSeriesResponse,
} from '../api/tickerIndicatorSeries';

export function indicatorSeriesQueryKey(
  symbol: string,
  name: IndicatorSeriesName,
): readonly unknown[] {
  return ['indicator-series', symbol, name];
}

export interface UseIndicatorSeriesOptions {
  enabled?: boolean;
}

export function useIndicatorSeries(
  symbol: string,
  name: IndicatorSeriesName,
  options: UseIndicatorSeriesOptions = {},
): UseQueryResult<IndicatorSeriesResponse> {
  const { enabled = true } = options;
  return useQuery({
    queryKey: indicatorSeriesQueryKey(symbol, name),
    queryFn: () => getIndicatorSeries(symbol, name),
    enabled: enabled && symbol.length > 0,
    refetchOnWindowFocus: false,
    staleTime: 60 * 1000,
    retry: 0,
  });
}
