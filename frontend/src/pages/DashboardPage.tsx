import { useMemo } from 'react';
import { Link } from 'react-router-dom';
import { LoadingSpinner } from '../components/LoadingSpinner';
import { ActionBadge } from '../components/ActionBadge';
import { SignalBadge, type SignalTone } from '../components/SignalBadge';
import { ProsConsList } from '../components/ProsConsList';
import { DataStatusBadge } from '../components/DataStatusBadge';
import { useMarketPosture } from '../hooks/useMarketPosture';
import {
  useDashboardWatchlistSignals,
  type WatchlistSignalRow,
} from '../hooks/useDashboardWatchlistSignals';
import type { ActionCategoryCode } from '../api/tickerSignal';
import { EisweinApiError } from '../api/errors';
import { ROUTES } from '../lib/constants';

const ATTENTION_ACTIONS: readonly ActionCategoryCode[] = ['strong_buy', 'reduce', 'exit'];

function dominantTone(
  greenCount: number,
  redCount: number,
): SignalTone {
  if (greenCount === 0 && redCount === 0) return 'neutral';
  if (greenCount > redCount) return 'green';
  if (redCount > greenCount) return 'red';
  return 'yellow';
}

function formatRefresh(refresh: Date | null): string {
  if (!refresh) return '尚未更新';
  return refresh.toLocaleString('zh-TW', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export function DashboardPage(): JSX.Element {
  return (
    <div className="flex flex-col gap-6">
      <section aria-labelledby="dashboard-heading" className="flex flex-col gap-1">
        <h1 id="dashboard-heading" className="text-2xl font-semibold">
          儀表板
        </h1>
        <p className="text-xs text-slate-500">
          所有數據基於最近交易日收盤後重算。市場態勢為全體共享狀態。
        </p>
      </section>

      <MarketPostureCard />
      <AttentionAlertsCard />
      <WatchlistOverviewCard />
      <PositionsPlaceholder />
    </div>
  );
}

function MarketPostureCard(): JSX.Element {
  const { data, isLoading, isError, error, refetch } = useMarketPosture();

  const content = useMemo(() => {
    if (isLoading) {
      return (
        <div className="flex items-center gap-2 text-slate-400">
          <LoadingSpinner label="載入市場態勢…" />
          <span className="text-sm">載入市場態勢…</span>
        </div>
      );
    }
    if (error instanceof EisweinApiError && error.status === 404) {
      return (
        <p role="status" className="text-sm text-slate-400">
          等待首次運算（每日收盤後產出）。
        </p>
      );
    }
    if (isError || !data) {
      return (
        <div className="flex items-center justify-between rounded-md border border-signal-red/40 bg-signal-red/10 px-3 py-2 text-sm text-signal-red">
          <span>無法載入市場態勢。</span>
          <button
            type="button"
            onClick={() => void refetch()}
            className="underline hover:text-signal-red"
          >
            重試
          </button>
        </div>
      );
    }

    return (
      <div className="flex flex-col gap-4">
        <div className="flex flex-wrap items-center gap-3">
          <span
            data-testid="market-posture-label"
            className="rounded-md border border-sky-500/40 bg-sky-500/10 px-3 py-1 text-lg font-semibold text-sky-300"
          >
            市場態勢：{data.posture_label}
          </span>
          {data.streak_badge && (
            <span className="rounded-full border border-slate-700 bg-slate-800 px-2.5 py-0.5 text-xs text-slate-200">
              {data.streak_badge}
            </span>
          )}
          <span className="text-xs text-slate-500">
            最近交易日：{data.date}
          </span>
        </div>
        <dl className="flex flex-wrap gap-4 text-sm">
          <RegimeCount tone="green" count={data.regime_green_count} label="進攻訊號" />
          <RegimeCount tone="yellow" count={data.regime_yellow_count} label="中性訊號" />
          <RegimeCount tone="red" count={data.regime_red_count} label="防守訊號" />
        </dl>
        <ProsConsList items={data.pros_cons} />
      </div>
    );
  }, [data, error, isError, isLoading, refetch]);

  return (
    <section
      aria-labelledby="market-posture-heading"
      className="flex flex-col gap-3 rounded-lg border border-slate-800 bg-slate-900/60 p-4"
    >
      <header>
        <h2 id="market-posture-heading" className="text-lg font-semibold">
          市場態勢
        </h2>
      </header>
      {content}
    </section>
  );
}

interface RegimeCountProps {
  tone: SignalTone;
  count: number;
  label: string;
}

function RegimeCount({ tone, count, label }: RegimeCountProps): JSX.Element {
  return (
    <div className="flex items-center gap-2">
      <SignalBadge tone={tone} ariaLabel={`${label}：${count} 個`} />
      <span className="text-slate-300">{count}</span>
    </div>
  );
}

function AttentionAlertsCard(): JSX.Element {
  const { rows, watchlistLoading } = useDashboardWatchlistSignals();
  const attention = useMemo(
    () =>
      rows.filter(
        (row) =>
          row.status === 'ready' &&
          row.signal !== null &&
          ATTENTION_ACTIONS.includes(row.signal.action),
      ),
    [rows],
  );

  return (
    <section
      aria-labelledby="attention-heading"
      className="flex flex-col gap-3 rounded-lg border border-slate-800 bg-slate-900/60 p-4"
    >
      <header>
        <h2 id="attention-heading" className="text-lg font-semibold">
          需要留意
        </h2>
      </header>
      {watchlistLoading && (
        <div className="flex items-center gap-2 text-slate-400">
          <LoadingSpinner label="載入觀察清單…" />
          <span className="text-sm">載入中…</span>
        </div>
      )}
      {!watchlistLoading && attention.length === 0 && (
        <p role="status" className="text-sm text-slate-400">
          沒有需要立即關注的訊號。
        </p>
      )}
      {attention.length > 0 && (
        <ul className="flex flex-col gap-2" data-testid="attention-list">
          {attention.map((row) => {
            const signal = row.signal;
            if (!signal) return null;
            return (
              <li key={row.item.symbol}>
                <Link
                  to={ROUTES.TICKER.replace(':symbol', row.item.symbol)}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-slate-800 bg-slate-950/40 px-3 py-2 text-sm hover:border-sky-500/40 hover:bg-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
                >
                  <span className="font-mono font-semibold text-slate-100">
                    {row.item.symbol}
                  </span>
                  <ActionBadge action={signal.action} timingBadge={signal.timing_badge} />
                  <span className="text-xs text-slate-400">
                    綠燈 {signal.direction_green_count} · 紅燈{' '}
                    {signal.direction_red_count}
                  </span>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

function WatchlistOverviewCard(): JSX.Element {
  const { rows, watchlistLoading, watchlistError, refetchWatchlist } =
    useDashboardWatchlistSignals();

  return (
    <section
      aria-labelledby="watchlist-overview-heading"
      className="flex flex-col gap-3 rounded-lg border border-slate-800 bg-slate-900/60 p-4"
    >
      <header className="flex items-baseline justify-between">
        <h2 id="watchlist-overview-heading" className="text-lg font-semibold">
          觀察清單
        </h2>
        <span className="text-xs text-slate-500">{rows.length} 個標的</span>
      </header>
      {watchlistLoading && (
        <div className="flex items-center gap-2 text-slate-400">
          <LoadingSpinner label="載入觀察清單…" />
          <span className="text-sm">載入中…</span>
        </div>
      )}
      {watchlistError && (
        <div className="flex items-center justify-between rounded-md border border-signal-red/40 bg-signal-red/10 px-3 py-2 text-sm text-signal-red">
          <span>載入觀察清單失敗。</span>
          <button
            type="button"
            onClick={() => void refetchWatchlist()}
            className="underline hover:text-signal-red"
          >
            重試
          </button>
        </div>
      )}
      {!watchlistLoading && !watchlistError && rows.length === 0 && (
        <p role="status" className="text-sm text-slate-400">
          尚未加入任何標的。請前往「設定」新增。
        </p>
      )}
      {rows.length > 0 && (
        <div className="overflow-hidden rounded-md border border-slate-800">
          <table className="w-full text-sm" data-testid="watchlist-table">
            <thead className="bg-slate-900/80 text-xs uppercase text-slate-400">
              <tr>
                <th scope="col" className="px-3 py-2 text-left">
                  代碼
                </th>
                <th scope="col" className="px-3 py-2 text-left">
                  建議動作
                </th>
                <th scope="col" className="px-3 py-2 text-left">
                  方向訊號
                </th>
                <th scope="col" className="px-3 py-2 text-left">
                  最近更新
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {rows.map((row) => (
                <WatchlistRow key={row.item.symbol} row={row} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

interface WatchlistRowProps {
  row: WatchlistSignalRow;
}

function WatchlistRow({ row }: WatchlistRowProps): JSX.Element {
  const { symbol } = row.item;
  const signal = row.signal;
  const tone: SignalTone = signal
    ? dominantTone(signal.direction_green_count, signal.direction_red_count)
    : 'neutral';

  return (
    <tr className="bg-slate-950/40 hover:bg-slate-900/60">
      <th scope="row" className="px-3 py-2 text-left font-mono font-semibold text-slate-100">
        <Link
          to={ROUTES.TICKER.replace(':symbol', symbol)}
          className="hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
        >
          {symbol}
        </Link>
      </th>
      <td className="px-3 py-2">
        {row.status === 'ready' && signal ? (
          <ActionBadge action={signal.action} timingBadge={signal.timing_badge} />
        ) : row.status === 'pending_signal' ? (
          <span className="text-xs text-slate-400">分析運算中</span>
        ) : row.status === 'loading' ? (
          <LoadingSpinner label="讀取訊號…" />
        ) : (
          <span className="text-xs text-signal-red">載入失敗</span>
        )}
      </td>
      <td className="px-3 py-2">
        {signal ? (
          <SignalBadge
            tone={tone}
            ariaLabel={`方向訊號：${signal.direction_green_count} 綠、${signal.direction_red_count} 紅`}
          />
        ) : (
          <DataStatusBadge status={row.item.dataStatus} />
        )}
      </td>
      <td className="px-3 py-2 text-xs text-slate-400">
        {formatRefresh(row.item.lastRefreshAt)}
      </td>
    </tr>
  );
}

function PositionsPlaceholder(): JSX.Element {
  return (
    <section
      aria-labelledby="positions-placeholder-heading"
      className="rounded-lg border border-dashed border-slate-800 bg-slate-900/40 p-4 text-sm text-slate-400"
    >
      <h2 id="positions-placeholder-heading" className="text-base font-semibold text-slate-300">
        持倉摘要
      </h2>
      <p className="mt-1">Phase 5 將填入持倉、資產配置與交易紀錄。</p>
    </section>
  );
}
