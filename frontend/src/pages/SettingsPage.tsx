import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { LoadingSpinner } from '../components/LoadingSpinner';
import { DataFreshnessBadge } from '../components/DataFreshnessBadge';
import { SchwabConnectCard } from '../components/SchwabConnectCard';
import {
  useAuditLog,
  useChangePassword,
  useDataRefresh,
  useSystemInfo,
} from '../hooks/useSettings';
import { EisweinApiError } from '../api/errors';
import type { AuditEntry } from '../api/settings';
import { relativeTime } from '../lib/time';

// Settings page — Commit C rewrite. WatchlistManager removed (sidebar handles
// add/remove/group/tag). System info compressed to 3 stat cards. Password
// + audit log live side-by-side on `lg`.

function formatBytes(bytes: number | null): string {
  if (bytes == null) return '—';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

const EVENT_LABELS: Record<string, string> = {
  login_success: '登入成功',
  login_failed: '登入失敗',
  logout: '登出',
  password_changed: '變更密碼',
  watchlist_added: '新增觀察標的',
  watchlist_removed: '移除觀察標的',
  manual_data_refresh: '手動更新資料',
};

export function SettingsPage(): JSX.Element {
  return (
    <div className="flex flex-col gap-6">
      <header>
        <h1 className="text-2xl font-bold tracking-tight text-stone-900">設定</h1>
        <p className="mt-1 text-sm text-stone-500">
          系統狀態、資料更新、密碼與稽核日誌。
        </p>
      </header>

      <SystemInfoCards />
      <DataRefreshCard />
      <SchwabConnectCard />
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <PasswordChangeCard />
        <AuditLogCard />
      </div>
      <p className="text-sm text-stone-500">
        觀察清單的新增、刪除、分組、標籤 → 請在左側側欄管理。
      </p>
    </div>
  );
}

function SystemInfoCards(): JSX.Element {
  const { data, isLoading, isError, refetch } = useSystemInfo();

  if (isLoading) {
    return (
      <div className="rounded-2xl border border-stone-200 bg-white p-4">
        <LoadingSpinner label="載入系統狀態…" />
      </div>
    );
  }
  if (isError || !data) {
    return (
      <div className="flex items-center justify-between rounded-2xl border border-rose-300 bg-rose-50 px-4 py-3 text-sm text-rose-700">
        <span>無法載入系統狀態。</span>
        <button type="button" onClick={() => void refetch()} className="underline">
          重試
        </button>
      </div>
    );
  }

  return (
    <div
      data-testid="system-info"
      className="grid grid-cols-1 gap-4 sm:grid-cols-3"
    >
      <StatCard label="資料庫大小" value={formatBytes(data.db_size_bytes)} />
      <StatCard
        label="最近資料更新"
        value={relativeTime(data.last_daily_update_at)}
      />
      <StatCard label="觀察標的數" value={String(data.watchlist_count)} />
    </div>
  );
}

interface StatCardProps {
  label: string;
  value: string;
}

function StatCard({ label, value }: StatCardProps): JSX.Element {
  return (
    <div className="rounded-2xl border border-stone-200 bg-white p-4">
      <dt className="text-xs text-stone-500">{label}</dt>
      <dd className="mt-1 font-mono text-xl text-stone-900">{value}</dd>
    </div>
  );
}

function DataRefreshCard(): JSX.Element {
  const mutation = useDataRefresh();
  const { data: sysInfo } = useSystemInfo();
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const onClick = async (): Promise<void> => {
    setSuccessMessage(null);
    setErrorMessage(null);
    try {
      const result = await mutation.mutateAsync();
      if (result.gaps_filled_rows > 0) {
        setSuccessMessage(
          `補齊了 ${result.gaps_filled_rows} 筆資料，覆蓋 ${result.gaps_filled_symbols} 個股票。`,
        );
      } else {
        setSuccessMessage(
          result.market_open
            ? '已是最新。'
            : '已是最新（今日市場未開盤，僅同步最近交易日）。',
        );
      }
    } catch (err) {
      if (err instanceof EisweinApiError) {
        if (err.code === 'rate_limited') {
          setErrorMessage('已達到更新頻率上限，請稍後再試（每小時 5 次）。');
          return;
        }
        setErrorMessage(err.message);
        return;
      }
      setErrorMessage('資料更新失敗，請稍後再試。');
    }
  };

  return (
    <section
      aria-labelledby="data-refresh-heading"
      className="flex flex-col gap-3 rounded-2xl border border-stone-200 bg-white p-6"
    >
      <header>
        <div className="flex flex-wrap items-center gap-2">
          <h2 id="data-refresh-heading" className="text-lg font-semibold">
            手動更新資料
          </h2>
          {sysInfo?.data_freshness && (
            <DataFreshnessBadge freshness={sysInfo.data_freshness} />
          )}
        </div>
        <p className="text-xs text-stone-500">
          觸發 daily_update 工作。每小時最多 5 次，同步可能耗時 10 秒以上。
        </p>
      </header>

      <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
        <button
          type="button"
          onClick={() => void onClick()}
          disabled={mutation.isPending}
          className="inline-flex items-center gap-2 self-start rounded-md bg-sky-600 px-4 py-2 text-sm font-semibold text-white hover:bg-sky-500 disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-300"
        >
          {mutation.isPending && <LoadingSpinner label="更新中…" />}
          <span>{mutation.isPending ? '更新中…' : '立即更新'}</span>
        </button>
        {successMessage && (
          <span role="status" className="text-sm text-emerald-700">
            {successMessage}
          </span>
        )}
        {errorMessage && (
          <span role="alert" className="text-sm text-rose-700">
            {errorMessage}
          </span>
        )}
      </div>
    </section>
  );
}

const passwordFormSchema = z
  .object({
    currentPassword: z.string().min(1, '請輸入目前密碼'),
    newPassword: z.string().min(12, '新密碼至少 12 字'),
    confirmPassword: z.string().min(1, '請再次輸入新密碼'),
  })
  .refine((v) => v.newPassword === v.confirmPassword, {
    path: ['confirmPassword'],
    message: '兩次輸入的新密碼不一致',
  });

type PasswordFormValues = z.infer<typeof passwordFormSchema>;

function PasswordChangeCard(): JSX.Element {
  const mutation = useChangePassword();
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitSuccess, setSubmitSuccess] = useState<string | null>(null);
  const [showCurrent, setShowCurrent] = useState(false);
  const [showNew, setShowNew] = useState(false);

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<PasswordFormValues>({
    resolver: zodResolver(passwordFormSchema),
    defaultValues: { currentPassword: '', newPassword: '', confirmPassword: '' },
  });

  const onSubmit = async (values: PasswordFormValues): Promise<void> => {
    setSubmitError(null);
    setSubmitSuccess(null);
    try {
      await mutation.mutateAsync({
        currentPassword: values.currentPassword,
        newPassword: values.newPassword,
      });
      setSubmitSuccess('密碼已更新。');
      reset();
    } catch (err) {
      if (err instanceof EisweinApiError) {
        if (err.status === 401 || err.code === 'invalid_credentials') {
          setSubmitError('目前密碼不正確。');
          return;
        }
        setSubmitError(err.message);
        return;
      }
      setSubmitError('密碼更新失敗，請稍後再試。');
    }
  };

  return (
    <section
      aria-labelledby="password-change-heading"
      className="flex flex-col gap-3 rounded-2xl border border-stone-200 bg-white p-6"
    >
      <header>
        <h2 id="password-change-heading" className="text-lg font-semibold">
          密碼變更
        </h2>
      </header>

      <form
        noValidate
        onSubmit={handleSubmit(onSubmit)}
        className="flex flex-col gap-4"
        autoComplete="off"
      >
        <div className="flex flex-col gap-1">
          <label htmlFor="current-password" className="text-sm font-medium text-stone-700">
            目前密碼
          </label>
          <div className="relative">
            <input
              id="current-password"
              type={showCurrent ? 'text' : 'password'}
              autoComplete="current-password"
              aria-invalid={Boolean(errors.currentPassword)}
              aria-describedby={
                errors.currentPassword ? 'current-password-error' : undefined
              }
              {...register('currentPassword')}
              className="w-full rounded-md border border-stone-300 bg-white px-3 py-2 pr-10 text-sm text-stone-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-500"
            />
            <ToggleVisibilityButton
              visible={showCurrent}
              onToggle={() => setShowCurrent((v) => !v)}
            />
          </div>
          {errors.currentPassword && (
            <p id="current-password-error" role="alert" className="text-xs text-rose-700">
              {errors.currentPassword.message}
            </p>
          )}
        </div>

        <div className="flex flex-col gap-1">
          <label htmlFor="new-password" className="text-sm font-medium text-stone-700">
            新密碼
          </label>
          <div className="relative">
            <input
              id="new-password"
              type={showNew ? 'text' : 'password'}
              autoComplete="new-password"
              aria-invalid={Boolean(errors.newPassword)}
              aria-describedby={
                errors.newPassword ? 'new-password-error' : 'new-password-hint'
              }
              {...register('newPassword')}
              className="w-full rounded-md border border-stone-300 bg-white px-3 py-2 pr-10 text-sm text-stone-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-500"
            />
            <ToggleVisibilityButton
              visible={showNew}
              onToggle={() => setShowNew((v) => !v)}
            />
          </div>
          <p id="new-password-hint" className="text-xs text-stone-500">
            至少 12 字元，請避免常見或與使用者名稱相關的密碼。
          </p>
          {errors.newPassword && (
            <p id="new-password-error" role="alert" className="text-xs text-rose-700">
              {errors.newPassword.message}
            </p>
          )}
        </div>

        <div className="flex flex-col gap-1">
          <label htmlFor="confirm-password" className="text-sm font-medium text-stone-700">
            確認新密碼
          </label>
          <input
            id="confirm-password"
            type="password"
            autoComplete="new-password"
            aria-invalid={Boolean(errors.confirmPassword)}
            aria-describedby={
              errors.confirmPassword ? 'confirm-password-error' : undefined
            }
            {...register('confirmPassword')}
            className="w-full rounded-md border border-stone-300 bg-white px-3 py-2 text-sm text-stone-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-500"
          />
          {errors.confirmPassword && (
            <p id="confirm-password-error" role="alert" className="text-xs text-rose-700">
              {errors.confirmPassword.message}
            </p>
          )}
        </div>

        {submitError && (
          <div
            role="alert"
            className="rounded-md border border-rose-300 bg-rose-50 px-3 py-2 text-sm text-rose-700"
          >
            {submitError}
          </div>
        )}
        {submitSuccess && (
          <div
            role="status"
            className="rounded-md border border-emerald-300 bg-emerald-50 px-3 py-2 text-sm text-emerald-700"
          >
            {submitSuccess}
          </div>
        )}

        <button
          type="submit"
          disabled={isSubmitting}
          className="inline-flex items-center gap-2 self-start rounded-md bg-sky-600 px-4 py-2 text-sm font-semibold text-white hover:bg-sky-500 disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-300"
        >
          {isSubmitting && <LoadingSpinner label="更新密碼中…" />}
          <span>{isSubmitting ? '更新中…' : '變更密碼'}</span>
        </button>
      </form>
    </section>
  );
}

interface ToggleVisibilityButtonProps {
  visible: boolean;
  onToggle: () => void;
}

function ToggleVisibilityButton({
  visible,
  onToggle,
}: ToggleVisibilityButtonProps): JSX.Element {
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-label={visible ? '隱藏密碼' : '顯示密碼'}
      aria-pressed={visible}
      className="absolute inset-y-0 right-0 flex items-center px-3 text-stone-500 hover:text-stone-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500 focus-visible:rounded-md"
    >
      <span aria-hidden="true">{visible ? '隱藏' : '顯示'}</span>
    </button>
  );
}

function AuditLogCard(): JSX.Element {
  const [limit, setLimit] = useState<number>(50);
  const { data, isLoading, isError, refetch } = useAuditLog(limit);

  return (
    <section
      aria-labelledby="audit-log-heading"
      className="flex flex-col gap-3 rounded-2xl border border-stone-200 bg-white p-6"
    >
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="audit-log-heading" className="text-lg font-semibold">
          稽核日誌
        </h2>
        {data && <span className="text-xs text-stone-400">{data.total} 筆</span>}
      </header>

      {isLoading && (
        <div className="flex items-center gap-2 text-stone-500">
          <LoadingSpinner label="載入稽核日誌…" />
          <span className="text-sm">載入中…</span>
        </div>
      )}
      {isError && (
        <div className="flex items-center justify-between rounded-md border border-rose-300 bg-rose-50 px-3 py-2 text-sm text-rose-700">
          <span>載入稽核日誌失敗。</span>
          <button type="button" onClick={() => void refetch()} className="underline">
            重試
          </button>
        </div>
      )}

      {data && data.data.length === 0 && !isLoading && (
        <p role="status" className="text-sm text-stone-500">
          尚無稽核紀錄。
        </p>
      )}

      {data && data.data.length > 0 && (
        <>
          <div className="overflow-hidden rounded-md border border-stone-200">
            <table className="w-full text-sm">
              <thead className="bg-stone-100 text-xs uppercase text-stone-500">
                <tr>
                  <th scope="col" className="px-3 py-2 text-left">
                    時間
                  </th>
                  <th scope="col" className="px-3 py-2 text-left">
                    事件
                  </th>
                  <th scope="col" className="px-3 py-2 text-left">
                    來源 IP
                  </th>
                  <th scope="col" className="px-3 py-2 text-left">
                    詳情
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-stone-200">
                {data.data.map((entry) => (
                  <AuditRow key={entry.id} entry={entry} />
                ))}
              </tbody>
            </table>
          </div>
          {data.data.length >= limit && (
            <button
              type="button"
              onClick={() => setLimit((n) => Math.min(n + 50, 500))}
              className="self-center rounded-md border border-stone-300 px-4 py-1.5 text-xs text-stone-700 hover:bg-stone-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500"
            >
              顯示更多
            </button>
          )}
        </>
      )}
    </section>
  );
}

function AuditRow({ entry }: { entry: AuditEntry }): JSX.Element {
  const label = EVENT_LABELS[entry.event_type] ?? entry.event_type;
  const outcome =
    typeof entry.details['outcome'] === 'string' ? entry.details['outcome'] : null;
  const date = new Date(entry.timestamp);
  const displayTime = Number.isNaN(date.getTime())
    ? entry.timestamp
    : date.toLocaleString('zh-TW', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
      });

  const summaryFields: string[] = [];
  if (outcome) summaryFields.push(outcome);
  const symbol = entry.details['symbol'];
  if (typeof symbol === 'string') summaryFields.push(symbol);

  return (
    <tr className="bg-white">
      <td className="px-3 py-2 text-xs text-stone-500">{displayTime}</td>
      <td className="px-3 py-2 text-sm text-stone-800">{label}</td>
      <td className="px-3 py-2 text-xs font-mono text-stone-500">{entry.ip ?? '—'}</td>
      <td className="px-3 py-2 text-xs text-stone-500">
        {summaryFields.length > 0 ? summaryFields.join(' · ') : ''}
      </td>
    </tr>
  );
}
