import { useQuery } from '@tanstack/react-query';
import {
  fetchTickerPrices,
  type PriceHistoryResponse,
  type PriceRange,
} from '../api/tickerPrices';

export function tickerPricesQueryKey(
  symbol: string,
  range: PriceRange,
): readonly unknown[] {
  return ['ticker', symbol, 'prices', range];
}

export function useTickerPrices(
  symbol: string | undefined,
  range: PriceRange,
): ReturnType<typeof useQuery<PriceHistoryResponse>> {
  return useQuery({
    queryKey: tickerPricesQueryKey(symbol ?? '', range),
    queryFn: () => fetchTickerPrices(symbol as string, range),
    enabled: typeof symbol === 'string' && symbol.length > 0,
    refetchOnWindowFocus: false,
    staleTime: 5 * 60 * 1000,
  });
}
