import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from '@tanstack/react-query';
import {
  getDriftStatus,
  revalidateIndicators,
  type DriftStatus,
  type RevalidateResponse,
} from '../api/indicators';

export const DRIFT_QUERY_KEY = ['indicators', 'drift'] as const;

export function useDriftStatus(): UseQueryResult<DriftStatus> {
  return useQuery({
    queryKey: DRIFT_QUERY_KEY,
    queryFn: getDriftStatus,
    refetchOnWindowFocus: true,
    staleTime: 60_000,
  });
}

export function useRevalidateIndicators(): ReturnType<
  typeof useMutation<RevalidateResponse, Error, void>
> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => revalidateIndicators(),
    onSuccess: () => {
      // Invalidate the drift query so subsequent reads pick up the
      // `running_revalidation_job_id` the server just assigned.
      void qc.invalidateQueries({ queryKey: DRIFT_QUERY_KEY });
    },
  });
}
