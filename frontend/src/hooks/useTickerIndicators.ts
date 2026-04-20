import { useQuery } from '@tanstack/react-query';
import {
  fetchTickerIndicators,
  type TickerIndicatorsResponse,
} from '../api/tickerIndicators';

export function tickerIndicatorsQueryKey(symbol: string): readonly unknown[] {
  return ['ticker', symbol, 'indicators'];
}

export function useTickerIndicators(
  symbol: string | undefined,
): ReturnType<typeof useQuery<TickerIndicatorsResponse>> {
  return useQuery({
    queryKey: tickerIndicatorsQueryKey(symbol ?? ''),
    queryFn: () => fetchTickerIndicators(symbol as string),
    enabled: typeof symbol === 'string' && symbol.length > 0,
    refetchOnWindowFocus: false,
    staleTime: 5 * 60 * 1000,
  });
}
