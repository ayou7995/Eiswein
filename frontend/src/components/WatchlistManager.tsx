import { useCallback, useState } from 'react';
import { EisweinApiError } from '../api/errors';
import type { Job } from '../api/jobs';
import type { WatchlistItem } from '../api/watchlist';
import { useJob, useCancelJob } from '../hooks/useJob';
import {
  useAddTicker,
  useRemoveTicker,
  useWatchlist,
} from '../hooks/useWatchlist';
import { TickerInput } from './TickerInput';
import { LoadingSpinner } from './LoadingSpinner';
import { Modal } from './Modal';
import { TICKER_SYMBOL_REGEX } from '../lib/schemas';

function formatDate(d: Date | null): string {
  if (!d) return '—';
  return d.toLocaleString('zh-TW', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

// Maps backend error codes to Chinese user-facing strings. Switching on
// `code` (stable machine identifier, never the message) follows the
// STAFF_REVIEW_DECISIONS.md B6 convention.
function addErrorMessage(err: unknown, symbol: string): string {
  if (err instanceof EisweinApiError) {
    switch (err.code) {
      case 'invalid_ticker':
        return `${symbol} 不是有效股票代碼`;
      case 'already_exists':
      case 'watchlist_duplicate':
        return `${symbol} 已在觀察清單`;
      case 'preflight_unavailable':
        return '網路錯誤，請稍後重試';
      case 'watchlist_full':
        return `觀察清單已滿（上限 ${String(err.details['max'] ?? 100)}）`;
      case 'rate_limited':
        return '請求過於頻繁，請稍後再試';
      case 'validation_error':
        return '股票代碼格式不正確（只允許大寫英數字、半形句點或連字號）';
      default:
        return err.message;
    }
  }
  return '發生未知錯誤，請重試';
}

function removeErrorMessage(err: unknown): string {
  if (err instanceof EisweinApiError) {
    if (err.code === 'spy_is_system') return 'SPY 為系統基準，無法移除';
    if (err.code === 'not_found') return '此標的已不在清單中';
    return err.message;
  }
  return '移除失敗，請稍後再試';
}

export function WatchlistManager(): JSX.Element {
  const { data, isLoading, isError, refetch } = useWatchlist();
  const addMutation = useAddTicker();

  const [draft, setDraft] = useState<string>('');
  const [addError, setAddError] = useState<string | null>(null);
  const [addSuccess, setAddSuccess] = useState<string | null>(null);
  const [rowError, setRowError] = useState<string | null>(null);

  const isValidSymbol = draft !== '' && TICKER_SYMBOL_REGEX.test(draft);
  const isPending = addMutation.isPending;

  const handleAdd = useCallback(async (): Promise<void> => {
    if (!isValidSymbol) return;
    const symbol = draft;
    setAddError(null);
    setAddSuccess(null);
    try {
      const result = await addMutation.mutateAsync(symbol);
      setDraft('');
      setAddSuccess(`已加入 ${result.data.symbol}，背景計算中`);
      window.setTimeout(() => {
        setAddSuccess((current) =>
          current === `已加入 ${result.data.symbol}，背景計算中` ? null : current,
        );
      }, 3000);
    } catch (err) {
      setAddError(addErrorMessage(err, symbol));
    }
  }, [addMutation, draft, isValidSymbol]);

  return (
    <section
      aria-labelledby="watchlist-heading"
      className="flex flex-col gap-4 rounded-lg border border-slate-800 bg-slate-900/60 p-4"
    >
      <header className="flex items-baseline justify-between">
        <h2 id="watchlist-heading" className="text-lg font-semibold text-slate-100">
          觀察清單
        </h2>
        {data && (
          <span className="text-xs text-slate-500">{data.total} 個標的</span>
        )}
      </header>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          void handleAdd();
        }}
        className="flex flex-col gap-2 sm:flex-row sm:items-center"
      >
        <label htmlFor="new-ticker" className="sr-only">
          輸入股票代碼
        </label>
        <TickerInput
          id="new-ticker"
          value={draft}
          onChange={setDraft}
          disabled={isPending}
          placeholder="輸入代碼（例如：AAPL）"
          className="flex-1"
        />
        <button
          type="submit"
          disabled={!isValidSymbol || isPending}
          className="inline-flex items-center justify-center gap-2 rounded-md bg-sky-600 px-4 py-2 text-sm font-semibold text-white hover:bg-sky-500 disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-300"
        >
          {isPending && <LoadingSpinner label="加入中…" />}
          <span>{isPending ? '加入中…' : '加入'}</span>
        </button>
      </form>

      {addError && (
        <p
          role="alert"
          data-testid="watchlist-add-error"
          className="text-xs text-signal-red"
        >
          {addError}
        </p>
      )}
      {addSuccess && (
        <p role="status" className="text-xs text-signal-green">
          {addSuccess}
        </p>
      )}

      {isLoading && (
        <div className="flex items-center gap-2 text-slate-400">
          <LoadingSpinner label="載入觀察清單…" />
          <span className="text-sm">載入觀察清單…</span>
        </div>
      )}

      {isError && (
        <div
          role="alert"
          className="flex items-center justify-between rounded-md border border-signal-red/40 bg-signal-red/10 px-3 py-2 text-sm text-signal-red"
        >
          <span>無法載入觀察清單。</span>
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
        <p className="text-sm text-slate-500">
          尚未加入任何標的。從上方輸入股票代碼開始。
        </p>
      )}

      {rowError && (
        <p role="alert" className="text-xs text-signal-red">
          {rowError}
        </p>
      )}

      {data && data.data.length > 0 && (
        <ul
          data-testid="watchlist-list"
          className="flex flex-col divide-y divide-slate-800 overflow-hidden rounded-md border border-slate-800"
        >
          {data.data.map((item) => (
            <WatchlistRow
              key={item.symbol}
              item={item}
              onRowError={setRowError}
            />
          ))}
        </ul>
      )}
    </section>
  );
}

interface WatchlistRowProps {
  item: WatchlistItem;
  onRowError: (message: string | null) => void;
}

function WatchlistRow({ item, onRowError }: WatchlistRowProps): JSX.Element {
  if (item.isSystem) {
    return <SystemRow item={item} />;
  }
  if (item.dataStatus === 'pending') {
    return (
      <PendingRow
        item={item}
        jobId={item.activeOnboardingJobId}
        onRowError={onRowError}
      />
    );
  }
  if (item.dataStatus === 'failed' || item.dataStatus === 'delisted') {
    return <FailedRow item={item} onRowError={onRowError} />;
  }
  return <ReadyRow item={item} onRowError={onRowError} />;
}

function SystemRow({ item }: { item: WatchlistItem }): JSX.Element {
  return (
    <li
      className="flex items-center justify-between gap-3 bg-slate-900/40 px-4 py-3"
      title="SPY 為系統基準，無法移除"
    >
      <div className="flex min-w-0 flex-col">
        <div className="flex items-center gap-2">
          <span className="font-mono text-base font-semibold text-slate-300">
            {item.symbol}
          </span>
          <span
            aria-label="系統基準"
            className="rounded-full border border-slate-600 bg-slate-800/80 px-2 py-0.5 text-[11px] font-medium text-slate-400"
          >
            系統基準
          </span>
        </div>
        <span className="text-xs text-slate-500">
          最近更新：{formatDate(item.lastRefreshAt)}
        </span>
      </div>
      <span
        aria-hidden="true"
        className="text-xs text-slate-600"
      >
        —
      </span>
    </li>
  );
}

function ReadyRow({
  item,
  onRowError,
}: {
  item: WatchlistItem;
  onRowError: (message: string | null) => void;
}): JSX.Element {
  const removeMutation = useRemoveTicker();
  const [confirming, setConfirming] = useState<boolean>(false);

  const handleRemove = useCallback(async (): Promise<void> => {
    setConfirming(false);
    onRowError(null);
    try {
      await removeMutation.mutateAsync(item.symbol);
    } catch (err) {
      onRowError(removeErrorMessage(err));
    }
  }, [removeMutation, item.symbol, onRowError]);

  return (
    <li className="flex items-center justify-between gap-3 bg-slate-900/40 px-4 py-3">
      <div className="flex min-w-0 flex-col">
        <div className="flex items-center gap-2">
          <span className="font-mono text-base font-semibold text-slate-100">
            {item.symbol}
          </span>
          <span
            aria-label="資料已就緒"
            className="rounded-full border border-signal-green/40 bg-signal-green/10 px-2 py-0.5 text-[11px] font-medium text-signal-green"
          >
            ready
          </span>
        </div>
        <span className="text-xs text-slate-500">
          最近更新：{formatDate(item.lastRefreshAt)}
        </span>
      </div>
      {confirming ? (
        <div className="flex items-center gap-2 text-xs">
          <span className="text-slate-300">確定要移除？</span>
          <button
            type="button"
            onClick={() => void handleRemove()}
            disabled={removeMutation.isPending}
            className="rounded-md border border-signal-red/40 bg-signal-red/10 px-2 py-1 text-signal-red hover:bg-signal-red/20 disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-signal-red/60"
          >
            是
          </button>
          <button
            type="button"
            onClick={() => setConfirming(false)}
            className="rounded-md border border-slate-700 bg-slate-800 px-2 py-1 text-slate-300 hover:bg-slate-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
          >
            否
          </button>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => setConfirming(true)}
          aria-label={`移除 ${item.symbol}`}
          className="rounded-md border border-slate-700 bg-slate-800 px-3 py-1.5 text-xs text-slate-300 hover:border-signal-red/40 hover:text-signal-red focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-signal-red/60"
        >
          <span aria-hidden="true">×</span>
        </button>
      )}
    </li>
  );
}

function FailedRow({
  item,
  onRowError,
}: {
  item: WatchlistItem;
  onRowError: (message: string | null) => void;
}): JSX.Element {
  const removeMutation = useRemoveTicker();
  const addMutation = useAddTicker();
  const [isWorking, setIsWorking] = useState<boolean>(false);
  const delisted = item.dataStatus === 'delisted';

  const handleRemove = useCallback(async (): Promise<void> => {
    onRowError(null);
    try {
      await removeMutation.mutateAsync(item.symbol);
    } catch (err) {
      onRowError(removeErrorMessage(err));
    }
  }, [removeMutation, item.symbol, onRowError]);

  const handleRetry = useCallback(async (): Promise<void> => {
    onRowError(null);
    setIsWorking(true);
    try {
      // Retry = remove + re-add. Gap-filled data stays in the DB because
      // the runner keeps the previously-written rows (see backend).
      await removeMutation.mutateAsync(item.symbol);
      await addMutation.mutateAsync(item.symbol);
    } catch (err) {
      onRowError(addErrorMessage(err, item.symbol));
    } finally {
      setIsWorking(false);
    }
  }, [removeMutation, addMutation, item.symbol, onRowError]);

  return (
    <li className="flex items-center justify-between gap-3 bg-slate-900/40 px-4 py-3">
      <div className="flex min-w-0 flex-col">
        <div className="flex items-center gap-2">
          <span
            className={`font-mono text-base font-semibold ${
              delisted ? 'text-slate-500' : 'text-slate-100'
            }`}
          >
            {item.symbol}
          </span>
          <span
            aria-label={delisted ? '已下市或無效' : '加入失敗'}
            className={`rounded-full border px-2 py-0.5 text-[11px] font-medium ${
              delisted
                ? 'border-slate-500/40 bg-slate-500/10 text-slate-400'
                : 'border-signal-yellow/40 bg-signal-yellow/10 text-signal-yellow'
            }`}
          >
            <span aria-hidden="true">{delisted ? '🚫 ' : '⚠ '}</span>
            {delisted ? '已下市' : '加入失敗'}
          </span>
        </div>
      </div>
      <div className="flex items-center gap-2">
        {!delisted && (
          <button
            type="button"
            onClick={() => void handleRetry()}
            disabled={isWorking}
            aria-label={`重試加入 ${item.symbol}`}
            className="rounded-md border border-slate-700 bg-slate-800 px-3 py-1.5 text-xs text-slate-200 hover:border-sky-500/40 hover:text-sky-300 disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
          >
            {isWorking ? '處理中…' : '重試'}
          </button>
        )}
        <button
          type="button"
          onClick={() => void handleRemove()}
          disabled={removeMutation.isPending || isWorking}
          aria-label={`移除 ${item.symbol}`}
          className="rounded-md border border-slate-700 bg-slate-800 px-3 py-1.5 text-xs text-slate-300 hover:border-signal-red/40 hover:text-signal-red disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-signal-red/60"
        >
          移除
        </button>
      </div>
    </li>
  );
}

function PendingRow({
  item,
  jobId,
  onRowError,
}: {
  item: WatchlistItem;
  jobId: number | null;
  onRowError: (message: string | null) => void;
}): JSX.Element {
  const removeMutation = useRemoveTicker();
  const cancelMutation = useCancelJob();
  const jobQuery = useJob(jobId);
  const job: Job | null = jobQuery.data ?? null;
  const [cancelOpen, setCancelOpen] = useState<boolean>(false);

  const processed = job?.processed_days ?? 0;
  const total = job?.total_days ?? 0;
  const pct = total === 0 ? 0 : Math.min(100, Math.round((processed / total) * 100));

  const handleConfirmCancel = useCallback(async (): Promise<void> => {
    setCancelOpen(false);
    onRowError(null);
    try {
      if (jobId !== null) {
        // Fire-and-forget cancel so the runner reads the flag at its
        // next cooperative checkpoint. The delete below is the
        // authoritative UI action.
        await cancelMutation.mutateAsync(jobId);
      }
      await removeMutation.mutateAsync(item.symbol);
    } catch (err) {
      onRowError(removeErrorMessage(err));
    }
  }, [cancelMutation, removeMutation, jobId, item.symbol, onRowError]);

  return (
    <li className="flex flex-col gap-2 bg-slate-900/40 px-4 py-3">
      <div className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-1">
          <div className="flex items-center gap-2">
            <span className="font-mono text-base font-semibold text-slate-100">
              {item.symbol}
            </span>
            <span
              aria-label="資料載入中"
              className="rounded-full border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[11px] font-medium text-amber-300"
            >
              <span aria-hidden="true">⏳ </span>
              {total > 0 ? `${pct}% (${processed}/${total} 天)` : '準備中…'}
            </span>
          </div>
        </div>
        <button
          type="button"
          onClick={() => setCancelOpen(true)}
          disabled={removeMutation.isPending || cancelMutation.isPending}
          aria-label={`取消加入 ${item.symbol}`}
          className="rounded-md border border-slate-700 bg-slate-800 px-3 py-1.5 text-xs text-slate-200 hover:border-signal-red/40 hover:text-signal-red disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-signal-red/60"
        >
          取消
        </button>
      </div>
      <div
        role="progressbar"
        aria-valuenow={processed}
        aria-valuemin={0}
        aria-valuemax={total || 1}
        aria-label={`${item.symbol} 下載進度`}
        className="h-1.5 w-full overflow-hidden rounded-full bg-slate-800"
      >
        <div
          className="h-full bg-sky-500 transition-all"
          style={{ width: `${pct}%` }}
        />
      </div>

      <Modal
        open={cancelOpen}
        onClose={() => setCancelOpen(false)}
        title="取消加入"
        labelledById={`cancel-add-${item.symbol}`}
      >
        <div className="flex flex-col gap-4">
          <p className="text-sm text-slate-200">
            確定要取消加入 <span className="font-mono">{item.symbol}</span>？已下載的資料會保留。
          </p>
          <div className="flex flex-wrap justify-end gap-2">
            <button
              type="button"
              onClick={() => setCancelOpen(false)}
              className="rounded-md border border-slate-700 px-4 py-2 text-sm text-slate-200 hover:bg-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
            >
              保留
            </button>
            <button
              type="button"
              onClick={() => void handleConfirmCancel()}
              disabled={removeMutation.isPending || cancelMutation.isPending}
              className="inline-flex items-center gap-2 rounded-md bg-signal-red/80 px-4 py-2 text-sm font-semibold text-white hover:bg-signal-red disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-signal-red/60"
            >
              {(removeMutation.isPending || cancelMutation.isPending) && (
                <LoadingSpinner label="取消中…" />
              )}
              <span>取消加入</span>
            </button>
          </div>
        </div>
      </Modal>
    </li>
  );
}
