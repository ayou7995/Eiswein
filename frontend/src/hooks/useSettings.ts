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
  getIndustrySyncPrompt,
  getIndustrySyncStatus,
  importIndustryEvents,
  type IndustrySyncImportResult,
  type IndustrySyncPromptResult,
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

export function useIndustrySyncPrompt(): ReturnType<
  typeof useQuery<IndustrySyncPromptResult>
> {
  // The prompt is interpolated server-side with today's date, but we
  // only fetch it when the user clicks "copy" so it's always fresh.
  return useQuery({
    queryKey: ['settings', 'industry-sync-prompt'] as const,
    queryFn: getIndustrySyncPrompt,
    refetchOnWindowFocus: false,
    // Prompt depends on today's date; treat anything older than 6 h as
    // stale so the next click after midnight UTC re-fetches.
    staleTime: 6 * 60 * 60 * 1000,
    // Don't auto-fetch on mount — let the operator click to reveal.
    enabled: false,
  });
}

export function useIndustryEventsImport(): ReturnType<
  typeof useMutation<IndustrySyncImportResult, Error, string>
> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (jsonText: string) => importIndustryEvents(jsonText),
    onSuccess: () => {
      // Successful import mutates calendar_event rows and
      // last_industry_sync_at — invalidate so the Settings card
      // refreshes and the calendar page picks up new entries.
      void qc.invalidateQueries({ queryKey: ['settings', 'industry-sync-status'] });
      void qc.invalidateQueries({ queryKey: ['calendar', 'events'] });
    },
  });
}
