import { useQuery } from '@tanstack/react-query';
import {
  fetchTickerSignal,
  type TickerSignalResponse,
} from '../api/tickerSignal';

export function tickerSignalQueryKey(symbol: string): readonly unknown[] {
  return ['ticker', symbol, 'signal'];
}

export function useTickerSignal(
  symbol: string | undefined,
): ReturnType<typeof useQuery<TickerSignalResponse>> {
  return useQuery({
    queryKey: tickerSignalQueryKey(symbol ?? ''),
    queryFn: () => fetchTickerSignal(symbol as string),
    enabled: typeof symbol === 'string' && symbol.length > 0,
    refetchOnWindowFocus: false,
    staleTime: 5 * 60 * 1000,
  });
}
