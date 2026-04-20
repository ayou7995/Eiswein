import { useQuery } from '@tanstack/react-query';
import {
  fetchMarketPosture,
  type MarketPostureResponse,
} from '../api/marketPosture';

export const MARKET_POSTURE_QUERY_KEY = ['market-posture'] as const;

export function useMarketPosture(): ReturnType<typeof useQuery<MarketPostureResponse>> {
  return useQuery({
    queryKey: MARKET_POSTURE_QUERY_KEY,
    queryFn: fetchMarketPosture,
    // Daily data — no need to refetch on focus. Staleness is bounded by
    // the daily_update job cadence.
    refetchOnWindowFocus: false,
    staleTime: 5 * 60 * 1000,
  });
}
