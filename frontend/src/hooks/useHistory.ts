import { useQuery } from '@tanstack/react-query';
import {
  decisions,
  marketPostureHistory,
  signalAccuracy,
  tickerSignalsHistory,
  type DecisionHistoryResponse,
  type PostureHistoryResponse,
  type SignalAccuracyHorizon,
  type SignalAccuracyResponse,
  type TickerSignalsResponse,
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
  days?: number,
): ReturnType<typeof useQuery<SignalAccuracyResponse>> {
  return useQuery({
    queryKey: ['history', 'signal-accuracy', symbol ?? '', horizon, days ?? 'all'] as const,
    queryFn: () => {
      if (!symbol) throw new Error('useSignalAccuracy called without symbol');
      return signalAccuracy(symbol, horizon, days);
    },
    enabled: typeof symbol === 'string' && symbol.length > 0,
    refetchOnWindowFocus: false,
    staleTime: 5 * 60 * 1000,
    // Hold the previous response while a new horizon/window combo is
    // refetching. Without this the conditional render block unmounts on
    // every selector click, the page collapses, and the user scrolls
    // back to the top — a UX bug the user explicitly flagged.
    placeholderData: (prev) => prev,
  });
}

export function useTickerSignals(
  symbol: string | null,
  days: number,
): ReturnType<typeof useQuery<TickerSignalsResponse>> {
  return useQuery({
    queryKey: ['history', 'ticker-signals', symbol ?? '', days] as const,
    queryFn: () => {
      if (!symbol) throw new Error('useTickerSignals called without symbol');
      return tickerSignalsHistory(symbol, days);
    },
    enabled: typeof symbol === 'string' && symbol.length > 0,
    refetchOnWindowFocus: false,
    staleTime: 5 * 60 * 1000,
    // Same placeholder strategy as useSignalAccuracy — keeps the chart
    // mounted across 90D / 180D / 365D switches.
    placeholderData: (prev) => prev,
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
