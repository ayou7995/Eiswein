import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  addToPosition,
  closePosition,
  createPosition,
  getPosition,
  listPositions,
  reducePosition,
  type AdjustPositionInput,
  type OpenPositionInput,
  type PositionResponse,
  type PositionsListResponse,
  type PositionWithTrades,
} from '../api/positions';

export function positionsQueryKey(includeClosed: boolean): readonly unknown[] {
  return ['positions', includeClosed] as const;
}

export function positionQueryKey(id: number): readonly unknown[] {
  return ['position', id] as const;
}

export function usePositions(
  includeClosed = false,
): ReturnType<typeof useQuery<PositionsListResponse>> {
  return useQuery({
    queryKey: positionsQueryKey(includeClosed),
    queryFn: () => listPositions(includeClosed),
    refetchOnWindowFocus: false,
    staleTime: 30_000,
  });
}

export function usePosition(
  id: number | null,
): ReturnType<typeof useQuery<PositionWithTrades>> {
  return useQuery({
    queryKey: positionQueryKey(id ?? -1),
    queryFn: () => {
      if (id == null) throw new Error('usePosition called without id');
      return getPosition(id);
    },
    enabled: id != null,
    refetchOnWindowFocus: false,
    staleTime: 30_000,
  });
}

function invalidatePositionsCaches(qc: ReturnType<typeof useQueryClient>): void {
  void qc.invalidateQueries({ queryKey: ['positions'] });
  void qc.invalidateQueries({ queryKey: ['position'] });
}

export function useCreatePosition(): ReturnType<
  typeof useMutation<PositionResponse, Error, OpenPositionInput>
> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: OpenPositionInput) => createPosition(input),
    onSuccess: () => {
      invalidatePositionsCaches(qc);
    },
  });
}

export interface AdjustMutationInput {
  id: number;
  input: AdjustPositionInput;
}

export function useAddToPosition(): ReturnType<
  typeof useMutation<PositionResponse, Error, AdjustMutationInput>
> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, input }: AdjustMutationInput) => addToPosition(id, input),
    onSuccess: () => {
      invalidatePositionsCaches(qc);
    },
  });
}

export function useReducePosition(): ReturnType<
  typeof useMutation<PositionResponse, Error, AdjustMutationInput>
> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, input }: AdjustMutationInput) => reducePosition(id, input),
    onSuccess: () => {
      invalidatePositionsCaches(qc);
    },
  });
}

export function useClosePosition(): ReturnType<
  typeof useMutation<unknown, Error, number>
> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => closePosition(id),
    onSuccess: () => {
      invalidatePositionsCaches(qc);
    },
  });
}
