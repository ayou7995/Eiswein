import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  disconnectSchwab,
  getSchwabStatus,
  testSchwabConnection,
  type SchwabStatus,
  type SchwabTestResult,
} from '../api/broker';

const STATUS_KEY = ['schwab', 'status'] as const;

export function useSchwabConnection(): ReturnType<typeof useQuery<SchwabStatus>> {
  return useQuery({
    queryKey: STATUS_KEY,
    queryFn: getSchwabStatus,
    refetchOnWindowFocus: false,
    staleTime: 60_000,
  });
}

export function useSchwabTest(): ReturnType<
  typeof useMutation<SchwabTestResult, Error, void>
> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => testSchwabConnection(),
    // The test call mutates last_test_* fields server-side even on failure —
    // invalidate regardless so the card's "上次測試" row reflects reality.
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: STATUS_KEY });
    },
  });
}

export function useSchwabDisconnect(): ReturnType<
  typeof useMutation<void, Error, void>
> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => disconnectSchwab(),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: STATUS_KEY });
    },
  });
}
