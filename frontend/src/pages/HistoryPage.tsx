import { useMemo, useState } from 'react';
import { LoadingSpinner } from '../components/LoadingSpinner';
import { PostureTimelineChart } from '../components/charts/PostureTimelineChart';
import { useDecisions, useMarketPostureHistory, useSignalAccuracy } from '../hooks/useHistory';
import { useWatchlist } from '../hooks/useWatchlist';
import {
  SIGNAL_ACCURACY_HORIZONS,
  type SignalAccuracyHorizon,
  type DecisionItem,
} from '../api/history';

const DAYS_OPTIONS: readonly number[] = [30, 90, 180, 365];

const ACTION_LABEL: Record<string, string> = {
  strong_buy: '強力買入',
  buy: '買入',
  hold: '持有',
  watch: '觀望',
  reduce: '減倉',
  exit: '出場',
};

function formatDateTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString('zh-TW', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export function HistoryPage(): JSX.Element {
  return (
    <div className="flex flex-col gap-6">
      <header>
        <h1 className="text-2xl font-semibold">歷史紀錄</h1>
        <p className="text-xs text-slate-500">
          市場態勢時間軸、訊號準確率與我的決策 vs Eiswein 建議對照。
        </p>
      </header>

      <MarketPostureSection />
      <SignalAccuracySection />
      <DecisionsSection />
    </div>
  );
}

function MarketPostureSection(): JSX.Element {
  const [days, setDays] = useState<number>(90);
  const { data, isLoading, isError, refetch } = useMarketPostureHistory(days);

  return (
    <section
      aria-labelledby="history-posture-heading"
      className="flex flex-col gap-3 rounded-lg border border-slate-800 bg-slate-900/60 p-4"
    >
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="history-posture-heading" className="text-lg font-semibold">
          市場態勢時間軸
        </h2>
        <div
          role="radiogroup"
          aria-label="區間"
          className="inline-flex rounded-md border border-slate-700 bg-slate-900/40 p-0.5"
        >
          {DAYS_OPTIONS.map((d) => {
            const active = d === days;
            return (
              <button
                key={d}
                type="button"
                role="radio"
                aria-checked={active}
                onClick={() => setDays(d)}
                className={`rounded px-3 py-1 text-xs font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400 ${
                  active ? 'bg-sky-600 text-white' : 'text-slate-300 hover:bg-slate-800 hover:text-white'
                }`}
              >
                {d}D
              </button>
            );
          })}
        </div>
      </header>

      {isLoading && (
        <div className="flex items-center gap-2 text-slate-400">
          <LoadingSpinner label="載入市場態勢歷史…" />
          <span className="text-sm">載入中…</span>
        </div>
      )}
      {isError && (
        <div className="flex items-center justify-between rounded-md border border-signal-red/40 bg-signal-red/10 px-3 py-2 text-sm text-signal-red">
          <span>載入市場態勢歷史失敗。</span>
          <button
            type="button"
            onClick={() => void refetch()}
            className="underline hover:text-signal-red"
          >
            重試
          </button>
        </div>
      )}
      {!isLoading && !isError && data && <PostureTimelineChart data={data.data} />}
    </section>
  );
}

function SignalAccuracySection(): JSX.Element {
  const watchlist = useWatchlist();
  const symbols = useMemo(
    () => (watchlist.data?.data.map((w) => w.symbol) ?? []).slice().sort((a, b) => a.localeCompare(b)),
    [watchlist.data],
  );
  const [symbol, setSymbol] = useState<string>('');
  const [horizon, setHorizon] = useState<SignalAccuracyHorizon>(5);

  const effectiveSymbol = symbol || symbols[0] || '';
  const { data, isLoading, isError, refetch } = useSignalAccuracy(
    effectiveSymbol || null,
    horizon,
  );

  return (
    <section
      aria-labelledby="history-accuracy-heading"
      className="flex flex-col gap-3 rounded-lg border border-slate-800 bg-slate-900/60 p-4"
    >
      <header>
        <h2 id="history-accuracy-heading" className="text-lg font-semibold">
          訊號準確率
        </h2>
        <p className="text-xs text-slate-500">以過去運算的建議動作與 N 日後收盤方向比對。</p>
      </header>

      <div className="flex flex-wrap items-center gap-3">
        <label className="flex flex-col gap-1 text-xs text-slate-400">
          <span>股票代碼</span>
          <select
            value={effectiveSymbol}
            onChange={(e) => setSymbol(e.target.value)}
            className="rounded-md border border-slate-700 bg-slate-800 px-3 py-1.5 text-sm text-slate-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
            aria-label="選擇股票代碼"
          >
            {symbols.length === 0 && <option value="">（觀察清單為空）</option>}
            {symbols.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        <fieldset className="flex flex-col gap-1 text-xs text-slate-400">
          <legend>時間範圍</legend>
          <div
            role="radiogroup"
            aria-label="準確率時間範圍"
            className="inline-flex rounded-md border border-slate-700 bg-slate-900/40 p-0.5"
          >
            {SIGNAL_ACCURACY_HORIZONS.map((h) => {
              const active = h === horizon;
              return (
                <button
                  key={h}
                  type="button"
                  role="radio"
                  aria-checked={active}
                  onClick={() => setHorizon(h)}
                  className={`rounded px-3 py-1 text-xs font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400 ${
                    active ? 'bg-sky-600 text-white' : 'text-slate-300 hover:bg-slate-800 hover:text-white'
                  }`}
                >
                  {h} 日
                </button>
              );
            })}
          </div>
        </fieldset>
      </div>

      {!effectiveSymbol && (
        <p role="status" className="text-sm text-slate-400">
          請先於「設定」加入觀察清單。
        </p>
      )}

      {effectiveSymbol && isLoading && (
        <div className="flex items-center gap-2 text-slate-400">
          <LoadingSpinner label="載入準確率…" />
          <span className="text-sm">載入中…</span>
        </div>
      )}
      {effectiveSymbol && isError && (
        <div className="flex items-center justify-between rounded-md border border-signal-red/40 bg-signal-red/10 px-3 py-2 text-sm text-signal-red">
          <span>載入準確率失敗。</span>
          <button
            type="button"
            onClick={() => void refetch()}
            className="underline hover:text-signal-red"
          >
            重試
          </button>
        </div>
      )}

      {effectiveSymbol && data && (
        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap items-baseline gap-3" data-testid="accuracy-headline">
            <span className="text-3xl font-semibold text-slate-100">
              {data.accuracy_pct.toFixed(1)}%
            </span>
            <span className="text-xs text-slate-400">
              {data.correct} / {data.total_signals} 次命中（{horizon} 日）
            </span>
          </div>
          {data.total_signals === 0 ? (
            <p role="status" className="text-sm text-slate-400">
              尚無足夠訊號可評估。
            </p>
          ) : (
            <div className="overflow-hidden rounded-md border border-slate-800">
              <table className="w-full text-sm">
                <thead className="bg-slate-900/80 text-xs uppercase text-slate-400">
                  <tr>
                    <th scope="col" className="px-3 py-2 text-left">
                      動作
                    </th>
                    <th scope="col" className="px-3 py-2 text-right">
                      次數
                    </th>
                    <th scope="col" className="px-3 py-2 text-right">
                      命中
                    </th>
                    <th scope="col" className="px-3 py-2 text-right">
                      準確率
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800">
                  {Object.entries(data.by_action).map(([action, bucket]) => (
                    <tr key={action} className="bg-slate-950/40">
                      <th scope="row" className="px-3 py-2 text-left font-medium text-slate-200">
                        {ACTION_LABEL[action] ?? action}
                      </th>
                      <td className="px-3 py-2 text-right font-mono text-slate-300">
                        {bucket.total}
                      </td>
                      <td className="px-3 py-2 text-right font-mono text-slate-300">
                        {bucket.correct}
                      </td>
                      <td className="px-3 py-2 text-right font-mono text-slate-200">
                        {bucket.accuracy_pct.toFixed(1)}%
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function DecisionsSection(): JSX.Element {
  const [limit, setLimit] = useState<number>(30);
  const { data, isLoading, isError, refetch } = useDecisions(limit);

  return (
    <section
      aria-labelledby="history-decisions-heading"
      className="flex flex-col gap-3 rounded-lg border border-slate-800 bg-slate-900/60 p-4"
    >
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="history-decisions-heading" className="text-lg font-semibold">
          我的決策 vs Eiswein
        </h2>
        <span className="text-xs text-slate-500">近 {limit} 筆交易</span>
      </header>

      {isLoading && (
        <div className="flex items-center gap-2 text-slate-400">
          <LoadingSpinner label="載入決策紀錄…" />
          <span className="text-sm">載入中…</span>
        </div>
      )}
      {isError && (
        <div className="flex items-center justify-between rounded-md border border-signal-red/40 bg-signal-red/10 px-3 py-2 text-sm text-signal-red">
          <span>載入決策紀錄失敗。</span>
          <button
            type="button"
            onClick={() => void refetch()}
            className="underline hover:text-signal-red"
          >
            重試
          </button>
        </div>
      )}

      {!isLoading && !isError && data && data.data.length === 0 && (
        <p role="status" className="text-sm text-slate-400">
          尚無交易紀錄可對照。
        </p>
      )}

      {data && data.data.length > 0 && (
        <>
          <div className="overflow-hidden rounded-md border border-slate-800">
            <table className="w-full text-sm">
              <thead className="bg-slate-900/80 text-xs uppercase text-slate-400">
                <tr>
                  <th scope="col" className="px-3 py-2 text-left">
                    日期
                  </th>
                  <th scope="col" className="px-3 py-2 text-left">
                    代碼
                  </th>
                  <th scope="col" className="px-3 py-2 text-left">
                    我做的
                  </th>
                  <th scope="col" className="px-3 py-2 text-left">
                    Eiswein 建議
                  </th>
                  <th scope="col" className="px-3 py-2 text-center">
                    符合
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800">
                {data.data.map((item) => (
                  <DecisionRow key={item.trade_id} item={item} />
                ))}
              </tbody>
            </table>
          </div>
          {data.data.length >= limit && (
            <button
              type="button"
              onClick={() => setLimit((n) => Math.min(n + 30, 200))}
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

function DecisionRow({ item }: { item: DecisionItem }): JSX.Element {
  const sideLabel = item.side === 'buy' ? '買' : '賣';
  const match = item.matched_recommendation;
  return (
    <tr className="bg-slate-950/40">
      <td className="px-3 py-2 text-xs text-slate-400">{formatDateTime(item.trade_date)}</td>
      <th scope="row" className="px-3 py-2 text-left font-mono font-semibold text-slate-100">
        {item.symbol}
      </th>
      <td className="px-3 py-2 text-slate-200">
        <span
          className={`rounded px-2 py-0.5 text-xs font-semibold ${
            item.side === 'buy'
              ? 'bg-signal-green/15 text-signal-green'
              : 'bg-signal-red/15 text-signal-red'
          }`}
          aria-label={`${sideLabel}單`}
        >
          {sideLabel}
        </span>
      </td>
      <td className="px-3 py-2 text-slate-200">
        {item.eiswein_action ? ACTION_LABEL[item.eiswein_action] ?? item.eiswein_action : '—'}
      </td>
      <td className="px-3 py-2 text-center">
        {match == null ? (
          <span className="text-slate-500" aria-label="無法比對">
            —
          </span>
        ) : match ? (
          <span className="text-signal-green" aria-label="符合建議">
            ✓
          </span>
        ) : (
          <span className="text-signal-red" aria-label="不符建議">
            ✗
          </span>
        )}
      </td>
    </tr>
  );
}
