import { useCallback, useState } from 'react';
import { TICKER_SYMBOL_REGEX } from '../lib/schemas';
import { useAddTicker, useRemoveTicker, useWatchlist } from '../hooks/useWatchlist';
import { EisweinApiError } from '../api/errors';
import type { WatchlistItem } from '../api/watchlist';
import { DataStatusBadge } from './DataStatusBadge';
import { LoadingSpinner } from './LoadingSpinner';
import { TickerInput } from './TickerInput';

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

function extractApiError(err: unknown): string {
  if (err instanceof EisweinApiError) {
    switch (err.code) {
      case 'watchlist_duplicate':
        return '此標的已經在 Watchlist 內。';
      case 'watchlist_full':
        return `Watchlist 已滿（上限 ${err.details['max'] ?? '100'}）。`;
      case 'rate_limited':
        return '請求過於頻繁，請稍後再試。';
      case 'validation_error':
        return '股票代碼格式不正確（只允許大寫英數字、半形句點或連字號）。';
      default:
        return err.message;
    }
  }
  return '發生未知錯誤，請重試。';
}

export function WatchlistSection(): JSX.Element {
  const { data, isLoading, isError, refetch } = useWatchlist();
  const addMutation = useAddTicker();
  const removeMutation = useRemoveTicker();

  const [draft, setDraft] = useState('');
  const [submitError, setSubmitError] = useState<string | null>(null);
  const isValidSymbol = draft !== '' && TICKER_SYMBOL_REGEX.test(draft);

  const handleAdd = useCallback(async () => {
    if (!isValidSymbol) return;
    setSubmitError(null);
    try {
      await addMutation.mutateAsync(draft);
      setDraft('');
    } catch (err) {
      setSubmitError(extractApiError(err));
    }
  }, [addMutation, draft, isValidSymbol]);

  const handleRemove = useCallback(
    async (symbol: string) => {
      if (!confirm(`確定要從 Watchlist 移除 ${symbol}？（歷史價格保留）`)) return;
      try {
        await removeMutation.mutateAsync(symbol);
      } catch (err) {
        setSubmitError(extractApiError(err));
      }
    },
    [removeMutation],
  );

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
          <span className="text-xs text-slate-500">
            {data.total} 個標的
          </span>
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
          新增股票代碼
        </label>
        <TickerInput
          id="new-ticker"
          value={draft}
          onChange={setDraft}
          placeholder="例如：SPY、QQQ、AAPL"
          className="flex-1"
        />
        <button
          type="submit"
          disabled={!isValidSymbol || addMutation.isPending}
          className="inline-flex items-center justify-center gap-2 rounded-md bg-sky-600 px-4 py-2 text-sm font-semibold text-white hover:bg-sky-500 disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-300"
        >
          {addMutation.isPending && <LoadingSpinner label="新增中…" />}
          <span>新增</span>
        </button>
      </form>

      {submitError && (
        <div
          role="alert"
          className="rounded-md border border-signal-red/40 bg-signal-red/10 px-3 py-2 text-sm text-signal-red"
        >
          {submitError}
        </div>
      )}

      {isLoading && (
        <div className="flex items-center gap-2 text-slate-400">
          <LoadingSpinner label="載入觀察清單…" />
          <span className="text-sm">載入觀察清單…</span>
        </div>
      )}

      {isError && (
        <div className="flex items-center justify-between rounded-md border border-signal-red/40 bg-signal-red/10 px-3 py-2 text-sm text-signal-red">
          <span>載入失敗。</span>
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

      {data && data.data.length > 0 && (
        <ul className="flex flex-col divide-y divide-slate-800 overflow-hidden rounded-md border border-slate-800">
          {data.data.map((item) => (
            <WatchlistRow
              key={item.symbol}
              item={item}
              onRemove={handleRemove}
              removing={removeMutation.isPending && removeMutation.variables === item.symbol}
            />
          ))}
        </ul>
      )}
    </section>
  );
}

interface WatchlistRowProps {
  item: WatchlistItem;
  onRemove: (symbol: string) => void | Promise<void>;
  removing: boolean;
}

function WatchlistRow({ item, onRemove, removing }: WatchlistRowProps): JSX.Element {
  return (
    <li className="flex items-center justify-between gap-3 bg-slate-900/40 px-4 py-3">
      <div className="flex min-w-0 flex-col">
        <div className="flex items-center gap-2">
          <span className="font-mono text-base font-semibold text-slate-100">
            {item.symbol}
          </span>
          <DataStatusBadge status={item.dataStatus} />
        </div>
        <span className="text-xs text-slate-500">
          最近更新：{formatDate(item.lastRefreshAt)}
        </span>
      </div>
      <button
        type="button"
        onClick={() => void onRemove(item.symbol)}
        disabled={removing}
        aria-label={`移除 ${item.symbol}`}
        className="rounded-md border border-slate-700 bg-slate-800 px-3 py-1.5 text-xs text-slate-300 hover:border-signal-red/40 hover:text-signal-red disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-signal-red/60"
      >
        {removing ? '移除中…' : '移除'}
      </button>
    </li>
  );
}
