import { useEffect, useRef } from 'react';
import { useMutation, useQuery, useQueryClient, type UseQueryResult } from '@tanstack/react-query';
import {
  cancelJob,
  getJob,
  isTerminalJobState,
  type Job,
} from '../api/jobs';

// 2500ms balances responsiveness (moving progress bar) against server
// load. Matches the cadence used in Phase 0's backfill card.
const ACTIVE_POLL_MS = 2500;

export const JOB_QUERY_KEY_ROOT = ['job'] as const;

export function jobQueryKey(jobId: number | null): readonly (string | number)[] {
  return [...JOB_QUERY_KEY_ROOT, jobId ?? 'none'];
}

export function useJob(jobId: number | null): UseQueryResult<Job> {
  const qc = useQueryClient();
  const result = useQuery({
    queryKey: jobQueryKey(jobId),
    queryFn: () => {
      if (jobId === null) {
        throw new Error('useJob called without jobId');
      }
      return getJob(jobId);
    },
    enabled: jobId !== null,
    // Poll only while the job is running. Terminal states stop the
    // interval so we don't hit the API in the background forever.
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data) return ACTIVE_POLL_MS;
      return isTerminalJobState(data.state) ? false : ACTIVE_POLL_MS;
    },
    refetchOnWindowFocus: false,
    staleTime: 0,
  });

  // Fire-once invalidation when the job reaches a terminal state so
  // downstream pages (history accuracy, market-posture timeline,
  // watchlist freshness) pick up new ticker_snapshot rows without
  // requiring the user to hard-reload. The ref guards against multiple
  // invalidations if the query re-renders after terminal arrival.
  const lastStateRef = useRef<string | null>(null);
  useEffect(() => {
    const state = result.data?.state ?? null;
    if (state && state !== lastStateRef.current && isTerminalJobState(state)) {
      lastStateRef.current = state;
      if (state === 'completed') {
        qc.invalidateQueries({ queryKey: ['history'] });
        qc.invalidateQueries({ queryKey: ['watchlist'] });
        qc.invalidateQueries({ queryKey: ['drift-status'] });
      }
    } else if (state !== lastStateRef.current) {
      lastStateRef.current = state;
    }
  }, [result.data?.state, qc]);

  return result;
}

export function useCancelJob(): ReturnType<
  typeof useMutation<Job, Error, number>
> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (jobId: number) => cancelJob(jobId),
    onSuccess: (job) => {
      qc.setQueryData(jobQueryKey(job.id), job);
    },
  });
}
