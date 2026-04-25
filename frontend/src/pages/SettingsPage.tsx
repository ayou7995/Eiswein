import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { LoadingSpinner } from '../components/LoadingSpinner';
import { SchwabConnectCard } from '../components/SchwabConnectCard';
import { WatchlistManager } from '../components/WatchlistManager';
import { useAuditLog, useChangePassword, useDataRefresh, useSystemInfo } from '../hooks/useSettings';
import { EisweinApiError } from '../api/errors';
import type { AuditEntry } from '../api/settings';
import { relativeTime } from '../lib/time';

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
  position_opened: '開倉',
  position_add: '加碼',
  position_reduce: '減碼',
  position_closed: '關閉持倉',
  watchlist_added: '新增觀察標的',
  watchlist_removed: '移除觀察標的',
  manual_data_refresh: '手動更新資料',
};

export function SettingsPage(): JSX.Element {
  return (
    <div className="flex flex-col gap-6">
      <header>
        <h1 className="text-2xl font-semibold text-slate-100">設定</h1>
        <p className="mt-1 text-sm text-slate-400">系統狀態、資料更新、觀察清單、密碼與稽核日誌。</p>
      </header>

      <SystemInfoCard />
      <SchwabConnectCard />
      <DataRefreshCard />
      <WatchlistManager />
      <PasswordChangeCard />
      <AuditLogCard />
    </div>
  );
}

function SystemInfoCard(): JSX.Element {
  const { data, isLoading, isError, refetch } = useSystemInfo();

  return (
    <section
      aria-labelledby="system-info-heading"
      className="flex flex-col gap-3 rounded-lg border border-slate-800 bg-slate-900/60 p-4"
    >
      <header>
        <h2 id="system-info-heading" className="text-lg font-semibold">
          系統狀態
        </h2>
      </header>

      {isLoading && (
        <div className="flex items-center gap-2 text-slate-400">
          <LoadingSpinner label="載入系統狀態…" />
          <span className="text-sm">載入中…</span>
        </div>
      )}
      {isError && (
        <div className="flex items-center justify-between rounded-md border border-signal-red/40 bg-signal-red/10 px-3 py-2 text-sm text-signal-red">
          <span>無法載入系統狀態。</span>
          <button
            type="button"
            onClick={() => void refetch()}
            className="underline hover:text-signal-red"
          >
            重試
          </button>
        </div>
      )}
      {data && (
        <dl
          data-testid="system-info"
          className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3"
        >
          <InfoStat label="資料庫大小" value={formatBytes(data.db_size_bytes)} />
          <InfoStat label="最近資料更新" value={relativeTime(data.last_daily_update_at)} />
          <InfoStat label="最近備份" value={relativeTime(data.last_backup_at)} />
          <InfoStat label="觀察標的數" value={String(data.watchlist_count)} />
          <InfoStat label="持倉數" value={String(data.positions_count)} />
          <InfoStat label="交易筆數" value={String(data.trade_count)} />
        </dl>
      )}
    </section>
  );
}

interface InfoStatProps {
  label: string;
  value: string;
}

function InfoStat({ label, value }: InfoStatProps): JSX.Element {
  return (
    <div className="rounded-md border border-slate-800 bg-slate-950/40 p-3">
      <dt className="text-xs text-slate-400">{label}</dt>
      <dd className="mt-0.5 font-mono text-sm text-slate-100">{value}</dd>
    </div>
  );
}

function DataRefreshCard(): JSX.Element {
  const mutation = useDataRefresh();
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
          setErrorMessage('已達到更新頻率上限，請稍後再試（每小時 1 次）。');
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
      className="flex flex-col gap-3 rounded-lg border border-slate-800 bg-slate-900/60 p-4"
    >
      <header>
        <h2 id="data-refresh-heading" className="text-lg font-semibold">
          手動更新資料
        </h2>
        <p className="text-xs text-slate-500">
          觸發 daily_update 工作。每小時最多一次，同步可能耗時 10 秒以上。
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
          <span role="status" className="text-sm text-signal-green">
            {successMessage}
          </span>
        )}
        {errorMessage && (
          <span role="alert" className="text-sm text-signal-red">
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
        // 422 strength violations come back with a pre-translated message.
        setSubmitError(err.message);
        return;
      }
      setSubmitError('密碼更新失敗，請稍後再試。');
    }
  };

  return (
    <section
      aria-labelledby="password-change-heading"
      className="flex flex-col gap-3 rounded-lg border border-slate-800 bg-slate-900/60 p-4"
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
          <label htmlFor="current-password" className="text-sm font-medium text-slate-300">
            目前密碼
          </label>
          <div className="relative">
            <input
              id="current-password"
              type={showCurrent ? 'text' : 'password'}
              autoComplete="current-password"
              aria-invalid={Boolean(errors.currentPassword)}
              aria-describedby={errors.currentPassword ? 'current-password-error' : undefined}
              {...register('currentPassword')}
              className="w-full rounded-md border border-slate-700 bg-slate-800 px-3 py-2 pr-10 text-sm text-slate-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
            />
            <ToggleVisibilityButton
              visible={showCurrent}
              onToggle={() => setShowCurrent((v) => !v)}
            />
          </div>
          {errors.currentPassword && (
            <p id="current-password-error" role="alert" className="text-xs text-signal-red">
              {errors.currentPassword.message}
            </p>
          )}
        </div>

        <div className="flex flex-col gap-1">
          <label htmlFor="new-password" className="text-sm font-medium text-slate-300">
            新密碼
          </label>
          <div className="relative">
            <input
              id="new-password"
              type={showNew ? 'text' : 'password'}
              autoComplete="new-password"
              aria-invalid={Boolean(errors.newPassword)}
              aria-describedby={errors.newPassword ? 'new-password-error' : 'new-password-hint'}
              {...register('newPassword')}
              className="w-full rounded-md border border-slate-700 bg-slate-800 px-3 py-2 pr-10 text-sm text-slate-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
            />
            <ToggleVisibilityButton
              visible={showNew}
              onToggle={() => setShowNew((v) => !v)}
            />
          </div>
          <p id="new-password-hint" className="text-xs text-slate-500">
            至少 12 字元，請避免常見或與使用者名稱相關的密碼。
          </p>
          {errors.newPassword && (
            <p id="new-password-error" role="alert" className="text-xs text-signal-red">
              {errors.newPassword.message}
            </p>
          )}
        </div>

        <div className="flex flex-col gap-1">
          <label htmlFor="confirm-password" className="text-sm font-medium text-slate-300">
            確認新密碼
          </label>
          <input
            id="confirm-password"
            type="password"
            autoComplete="new-password"
            aria-invalid={Boolean(errors.confirmPassword)}
            aria-describedby={errors.confirmPassword ? 'confirm-password-error' : undefined}
            {...register('confirmPassword')}
            className="w-full rounded-md border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
          />
          {errors.confirmPassword && (
            <p id="confirm-password-error" role="alert" className="text-xs text-signal-red">
              {errors.confirmPassword.message}
            </p>
          )}
        </div>

        {submitError && (
          <div
            role="alert"
            className="rounded-md border border-signal-red/40 bg-signal-red/10 px-3 py-2 text-sm text-signal-red"
          >
            {submitError}
          </div>
        )}
        {submitSuccess && (
          <div role="status" className="rounded-md border border-signal-green/40 bg-signal-green/10 px-3 py-2 text-sm text-signal-green">
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
      className="absolute inset-y-0 right-0 flex items-center px-3 text-slate-400 hover:text-slate-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400 focus-visible:rounded-md"
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
      className="flex flex-col gap-3 rounded-lg border border-slate-800 bg-slate-900/60 p-4"
    >
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="audit-log-heading" className="text-lg font-semibold">
          稽核日誌
        </h2>
        {data && (
          <span className="text-xs text-slate-500">{data.total} 筆</span>
        )}
      </header>

      {isLoading && (
        <div className="flex items-center gap-2 text-slate-400">
          <LoadingSpinner label="載入稽核日誌…" />
          <span className="text-sm">載入中…</span>
        </div>
      )}
      {isError && (
        <div className="flex items-center justify-between rounded-md border border-signal-red/40 bg-signal-red/10 px-3 py-2 text-sm text-signal-red">
          <span>載入稽核日誌失敗。</span>
          <button
            type="button"
            onClick={() => void refetch()}
            className="underline hover:text-signal-red"
          >
            重試
          </button>
        </div>
      )}

      {data && data.data.length === 0 && !isLoading && (
        <p role="status" className="text-sm text-slate-400">
          尚無稽核紀錄。
        </p>
      )}

      {data && data.data.length > 0 && (
        <>
          <div className="overflow-hidden rounded-md border border-slate-800">
            <table className="w-full text-sm">
              <thead className="bg-slate-900/80 text-xs uppercase text-slate-400">
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
              <tbody className="divide-y divide-slate-800">
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
              className="self-center rounded-md border border-slate-700 px-4 py-1.5 text-xs text-slate-200 hover:bg-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
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
  const outcome = typeof entry.details['outcome'] === 'string' ? entry.details['outcome'] : null;
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

  // Only surface whitelisted primitive fields to avoid dumping raw
  // JSON at the user. Longer payloads can be explored in server logs.
  const summaryFields: string[] = [];
  if (outcome) summaryFields.push(outcome);
  const symbol = entry.details['symbol'];
  if (typeof symbol === 'string') summaryFields.push(symbol);

  return (
    <tr className="bg-slate-950/40">
      <td className="px-3 py-2 text-xs text-slate-400">{displayTime}</td>
      <td className="px-3 py-2 text-sm text-slate-200">{label}</td>
      <td className="px-3 py-2 text-xs font-mono text-slate-400">{entry.ip ?? '—'}</td>
      <td className="px-3 py-2 text-xs text-slate-400">
        {summaryFields.length > 0 ? summaryFields.join(' · ') : ''}
      </td>
    </tr>
  );
}
