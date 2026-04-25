import { useCallback, useEffect, useState } from 'react';
import { EisweinApiError } from '../api/errors';
import { isTerminalJobState, type Job } from '../api/jobs';
import { useJob } from '../hooks/useJob';
import {
  DRIFT_QUERY_KEY,
  useDriftStatus,
  useRevalidateIndicators,
} from '../hooks/useIndicatorDrift';
import { useQueryClient } from '@tanstack/react-query';
import { LoadingSpinner } from './LoadingSpinner';

// Session-scoped dismiss key — baked with the current drift "generation"
// so a brand-new drift (different stale version set) shows again even
// if the user dismissed the previous one.
const DISMISS_KEY_PREFIX = 'eiswein.drift.dismissed';

function dismissKey(currentVersion: string): string {
  return `${DISMISS_KEY_PREFIX}.${currentVersion}`;
}

function readDismissed(currentVersion: string): boolean {
  if (typeof window === 'undefined') return false;
  try {
    return window.sessionStorage.getItem(dismissKey(currentVersion)) === 'true';
  } catch {
    return false;
  }
}

function writeDismissed(currentVersion: string, value: boolean): void {
  if (typeof window === 'undefined') return;
  try {
    if (value) {
      window.sessionStorage.setItem(dismissKey(currentVersion), 'true');
    } else {
      window.sessionStorage.removeItem(dismissKey(currentVersion));
    }
  } catch {
    // Swallow: dismiss persistence is a nice-to-have, not load-bearing.
  }
}

export function IndicatorDriftBanner(): JSX.Element | null {
  const driftQuery = useDriftStatus();
  const revalidateMutation = useRevalidateIndicators();
  const qc = useQueryClient();

  // `activeJobId` drives the polling hook. We initialise from the
  // server-side `running_revalidation_job_id` on first fetch so a
  // page reload mid-revalidation immediately shows progress.
  const [activeJobId, setActiveJobId] = useState<number | null>(null);
  const [mutationError, setMutationError] = useState<string | null>(null);
  // `dismissed` is seeded from sessionStorage when the drift payload
  // arrives (or changes version) so dismissal survives a reload. We
  // hold it in component state so re-renders stay in sync — reading
  // sessionStorage directly on every render made "dismiss" invisible
  // to React's reconciler.
  const [dismissed, setDismissed] = useState<boolean>(false);

  const drift = driftQuery.data ?? null;

  useEffect(() => {
    if (!drift) return;
    setDismissed(readDismissed(drift.current_version));
    if (drift.running_revalidation_job_id !== null && activeJobId === null) {
      setActiveJobId(drift.running_revalidation_job_id);
    }
  }, [drift, activeJobId]);

  const jobQuery = useJob(activeJobId);
  const job: Job | null = jobQuery.data ?? null;

  // When the job reaches a terminal state we refresh drift so the
  // banner can disappear (has_drift=false) or switch to a failure
  // state. Done here rather than in the job poll's onSuccess because
  // useJob is generic and shouldn't know about drift.
  useEffect(() => {
    if (!job) return;
    if (!isTerminalJobState(job.state)) return;
    // Successful revalidation clears both the banner and the dismiss
    // flag — the user should see a fresh drift warning if formulas
    // change again in the same session.
    if (job.state === 'completed' && drift) {
      writeDismissed(drift.current_version, false);
      setDismissed(false);
    }
    void qc.invalidateQueries({ queryKey: DRIFT_QUERY_KEY });
  }, [job, qc, drift]);

  const handleDismiss = useCallback((): void => {
    if (!drift) return;
    writeDismissed(drift.current_version, true);
    setDismissed(true);
  }, [drift]);

  const handleRevalidate = useCallback(async (): Promise<void> => {
    setMutationError(null);
    try {
      const result = await revalidateMutation.mutateAsync();
      setActiveJobId(result.job_id);
    } catch (err) {
      if (err instanceof EisweinApiError) {
        if (err.code === 'backfill_conflict') {
          setMutationError('另一個重算工作正在進行中。');
          return;
        }
        setMutationError(err.message);
        return;
      }
      setMutationError('重算失敗，請稍後再試。');
    }
  }, [revalidateMutation]);

  if (driftQuery.isLoading || !drift) return null;

  const inProgress = job !== null && !isTerminalJobState(job.state);
  const jobFailed = job !== null && job.state === 'failed';

  if (!drift.has_drift && !inProgress && !jobFailed) return null;

  // Dismissed: hide entirely unless a job is in-flight or failed
  // (those states need to stay visible regardless of dismiss).
  if (dismissed && !inProgress && !jobFailed) return null;

  if (jobFailed && job) {
    return (
      <div
        role="alert"
        data-testid="drift-banner-failed"
        className="flex flex-col gap-2 rounded-lg border border-signal-red/40 bg-signal-red/10 px-4 py-3 text-sm text-signal-red"
      >
        <span>
          <span aria-hidden="true">⚠</span> 重算失敗：
          {job.error ?? '未知原因'}
        </span>
        <button
          type="button"
          onClick={() => void handleRevalidate()}
          disabled={revalidateMutation.isPending}
          className="self-start rounded-md border border-signal-red/40 bg-signal-red/20 px-3 py-1 text-xs font-semibold text-signal-red hover:bg-signal-red/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-signal-red/60 disabled:cursor-not-allowed disabled:opacity-60"
        >
          再試一次
        </button>
      </div>
    );
  }

  if (inProgress && job) {
    const pct =
      job.total_days === 0
        ? 0
        : Math.min(100, Math.round((job.processed_days / job.total_days) * 100));
    return (
      <div
        role="status"
        data-testid="drift-banner-progress"
        className="flex flex-col gap-2 rounded-lg border border-sky-500/40 bg-sky-500/10 px-4 py-3 text-sm text-sky-200"
      >
        <div className="flex flex-wrap items-center gap-2">
          <LoadingSpinner label="重算中…" />
          <span className="font-semibold">
            重算中… {job.processed_days}/{job.total_days} 天
          </span>
          <span className="text-xs text-sky-300/80">（{pct}%）</span>
        </div>
        <div
          role="progressbar"
          aria-valuenow={job.processed_days}
          aria-valuemin={0}
          aria-valuemax={job.total_days}
          aria-label="指標重算進度"
          className="h-2 w-full overflow-hidden rounded-full bg-slate-800"
        >
          <div
            className="h-full bg-sky-500 transition-all"
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>
    );
  }

  return (
    <div
      role="alert"
      data-testid="drift-banner"
      className="flex flex-col gap-3 rounded-lg border border-signal-yellow/40 bg-signal-yellow/10 px-4 py-3 text-sm text-signal-yellow sm:flex-row sm:items-center sm:justify-between"
    >
      <span>
        <span aria-hidden="true">⚠ </span>
        指標公式已更新至 {drift.current_version}，{drift.stale_row_count} 筆歷史訊號為舊版本
      </span>
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => void handleRevalidate()}
          disabled={revalidateMutation.isPending}
          className="rounded-md bg-signal-yellow/20 px-3 py-1.5 text-xs font-semibold text-signal-yellow hover:bg-signal-yellow/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-signal-yellow/60 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {revalidateMutation.isPending ? '啟動中…' : '立即重算全部'}
        </button>
        <button
          type="button"
          onClick={handleDismiss}
          className="rounded-md border border-slate-700 bg-slate-900/60 px-3 py-1.5 text-xs font-semibold text-slate-300 hover:bg-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
        >
          稍後
        </button>
        {mutationError && (
          <span role="status" className="text-xs text-signal-red">
            {mutationError}
          </span>
        )}
      </div>
    </div>
  );
}
