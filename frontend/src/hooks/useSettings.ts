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
import {
  getIndustrySyncStatus,
  runIndustrySync,
  type IndustrySyncRunResult,
  type IndustrySyncStatusResult,
} from '../api/calendar';

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

export function useIndustrySyncStatus(): ReturnType<
  typeof useQuery<IndustrySyncStatusResult>
> {
  return useQuery({
    queryKey: ['settings', 'industry-sync-status'] as const,
    queryFn: getIndustrySyncStatus,
    refetchOnWindowFocus: false,
    staleTime: 60_000,
  });
}

export function useIndustrySyncRun(): ReturnType<
  typeof useMutation<IndustrySyncRunResult, Error, void>
> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => runIndustrySync(),
    onSuccess: () => {
      // The sync mutates calendar_event rows and the last_industry_sync_at
      // metadata key — invalidate both so the Settings card refreshes
      // and the calendar page picks up any new entries on next view.
      void qc.invalidateQueries({ queryKey: ['settings', 'industry-sync-status'] });
      void qc.invalidateQueries({ queryKey: ['calendar', 'events'] });
    },
  });
}
