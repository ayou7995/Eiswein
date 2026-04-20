import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  changePassword,
  listAuditLog,
  systemInfo,
  triggerDataRefresh,
  type AuditLogResponse,
  type DataRefreshResponse,
  type SystemInfoResponse,
} from '../api/settings';

export function useAuditLog(
  limit: number,
): ReturnType<typeof useQuery<AuditLogResponse>> {
  return useQuery({
    queryKey: ['settings', 'audit-log', limit] as const,
    queryFn: () => listAuditLog(limit),
    refetchOnWindowFocus: false,
    staleTime: 30_000,
  });
}

export function useSystemInfo(): ReturnType<typeof useQuery<SystemInfoResponse>> {
  return useQuery({
    queryKey: ['settings', 'system-info'] as const,
    queryFn: systemInfo,
    refetchOnWindowFocus: false,
    staleTime: 30_000,
  });
}

export interface ChangePasswordInput {
  currentPassword: string;
  newPassword: string;
}

export function useChangePassword(): ReturnType<
  typeof useMutation<void, Error, ChangePasswordInput>
> {
  return useMutation({
    mutationFn: (input: ChangePasswordInput) => changePassword(input),
  });
}

export function useDataRefresh(): ReturnType<
  typeof useMutation<DataRefreshResponse, Error, void>
> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => triggerDataRefresh(),
    onSuccess: () => {
      // A successful refresh updates last_daily_update_at + watchlist
      // timestamps; invalidate everything that depends on that.
      void qc.invalidateQueries({ queryKey: ['settings', 'system-info'] });
      void qc.invalidateQueries({ queryKey: ['watchlist'] });
      void qc.invalidateQueries({ queryKey: ['market-posture'] });
      void qc.invalidateQueries({ queryKey: ['ticker'] });
    },
  });
}
