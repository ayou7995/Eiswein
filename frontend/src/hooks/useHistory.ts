import { useQuery } from '@tanstack/react-query';
import {
  decisions,
  marketPostureHistory,
  signalAccuracy,
  type DecisionHistoryResponse,
  type PostureHistoryResponse,
  type SignalAccuracyHorizon,
  type SignalAccuracyResponse,
} from '../api/history';

export function useMarketPostureHistory(
  days: number,
): ReturnType<typeof useQuery<PostureHistoryResponse>> {
  return useQuery({
    queryKey: ['history', 'market-posture', days] as const,
    queryFn: () => marketPostureHistory(days),
    refetchOnWindowFocus: false,
    staleTime: 5 * 60 * 1000,
  });
}

export function useSignalAccuracy(
  symbol: string | null,
  horizon: SignalAccuracyHorizon,
): ReturnType<typeof useQuery<SignalAccuracyResponse>> {
  return useQuery({
    queryKey: ['history', 'signal-accuracy', symbol ?? '', horizon] as const,
    queryFn: () => {
      if (!symbol) throw new Error('useSignalAccuracy called without symbol');
      return signalAccuracy(symbol, horizon);
    },
    enabled: typeof symbol === 'string' && symbol.length > 0,
    refetchOnWindowFocus: false,
    staleTime: 5 * 60 * 1000,
  });
}

export function useDecisions(
  limit: number,
): ReturnType<typeof useQuery<DecisionHistoryResponse>> {
  return useQuery({
    queryKey: ['history', 'decisions', limit] as const,
    queryFn: () => decisions(limit),
    refetchOnWindowFocus: false,
    staleTime: 60 * 1000,
  });
}
