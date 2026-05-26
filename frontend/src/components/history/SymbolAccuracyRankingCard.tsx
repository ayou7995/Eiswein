import { useMemo } from 'react';
import { Link } from 'react-router-dom';
import { LoadingSpinner } from '../LoadingSpinner';
import { Explainable, RuleTable } from '../Explainable';
import { useSymbolAccuracyRanking } from '../../hooks/useHistory';
import { ROUTES } from '../../lib/constants';

interface SymbolAccuracyRankingCardProps {
  days: number;
}

// Per-symbol hit-rate ranking. Horizon is fixed at 20 trading days (≈1
// trading month — the O'Neil/Sherry-style core window the 12 indicators are
// tuned for). The ranking window follows the parent HistoryPage's range
// selector so the operator sees consistent slices everywhere on the page.
//
// Visualisation: horizontal accuracy bars with the baseline overlay as a
// faint reference line. Click a row → navigates to the ticker detail.
export function SymbolAccuracyRankingCard({
  days,
}: SymbolAccuracyRankingCardProps): JSX.Element {
  const { data, isLoading, isError, refetch } = useSymbolAccuracyRanking({
    days,
    horizon: 20,
  });

  const sorted = useMemo(() => {
    if (!data) return [];
    // The backend already sorts descending, but the schema is just an array
    // — defensive sort here keeps the UI stable if the server contract
    // ever loosens.
    return data.data
      .slice()
      .sort((a, b) => b.accuracy_pct - a.accuracy_pct);
  }, [data]);

  return (
    <section
      aria-labelledby="symbol-accuracy-ranking-heading"
      className="flex flex-col gap-3 rounded-2xl border border-stone-200 bg-white p-6"
    >
      <header>
        <h2
          id="symbol-accuracy-ranking-heading"
          className="text-lg font-semibold"
        >
          <Explainable
            title="各代碼命中率排行"
            explanation={
              <RuleTable
                preface="觀察清單中每個代碼，在所選範圍內的訊號 → 20 日後股價方向比對。命中率排序由高到低。"
                rows={[
                  {
                    condition: '橫條長度',
                    result: '0–100 % 命中率比例。淡色標線是同期 SPY baseline。',
                  },
                  {
                    condition: '0 / 「資料累積中」',
                    result: '所選範圍內該代碼沒有可評估的訊號。',
                  },
                ]}
                note="20 日是 horizon 標準值；可在個股詳細頁切換 5 / 60 / 120 日進階比較。"
              />
            }
          >
            各代碼命中率排行
          </Explainable>
        </h2>
        <p className="text-xs text-stone-500 mt-1">
          所選範圍：{days} 天 · horizon 20 日
        </p>
      </header>

      {isLoading && (
        <div className="flex items-center gap-2 text-stone-500">
          <LoadingSpinner label="載入排行…" />
          <span className="text-sm">載入中…</span>
        </div>
      )}
      {isError && (
        <div className="flex items-center justify-between rounded-md border border-rose-300 bg-rose-50 px-3 py-2 text-sm text-rose-700">
          <span>載入排行失敗。</span>
          <button
            type="button"
            onClick={() => void refetch()}
            className="underline"
          >
            重試
          </button>
        </div>
      )}

      {data && sorted.length === 0 && (
        <p role="status" className="text-sm text-stone-500">
          觀察清單為空，或所選範圍內無可評估的訊號。
        </p>
      )}

      {data && sorted.length > 0 && (
        <div className="flex flex-col gap-1">
          {sorted.map((entry) => {
            const hasSignals = entry.total_signals > 0;
            const pct = Math.max(0, Math.min(100, entry.accuracy_pct));
            const baselinePct = Math.max(
              0,
              Math.min(100, data.baseline.spy_up_pct),
            );
            return (
              <Link
                key={entry.symbol}
                to={ROUTES.TICKER.replace(':symbol', entry.symbol)}
                className="grid grid-cols-[80px_1fr_80px] items-center gap-3 rounded-md px-2 py-1.5 text-sm hover:bg-stone-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500"
              >
                <span className="font-mono font-semibold text-stone-900">
                  {entry.symbol}
                </span>
                <span
                  className="relative block h-3 overflow-hidden rounded-full bg-stone-100"
                  aria-label={`${entry.symbol} 命中率 ${entry.accuracy_pct.toFixed(1)}%`}
                >
                  {hasSignals && (
                    <span
                      aria-hidden="true"
                      className="absolute inset-y-0 left-0 rounded-full bg-emerald-500"
                      style={{ width: `${pct}%` }}
                    />
                  )}
                  {data.baseline.total > 0 && (
                    <span
                      aria-hidden="true"
                      className="absolute inset-y-0 w-0.5 bg-stone-500"
                      style={{ left: `${baselinePct}%` }}
                    />
                  )}
                </span>
                <span className="text-right font-mono tabular-nums text-stone-700">
                  {hasSignals ? `${entry.accuracy_pct.toFixed(1)}%` : '資料累積中'}
                </span>
              </Link>
            );
          })}
          {data.baseline.total > 0 && (
            <p className="mt-2 text-xs text-stone-500">
              <span aria-hidden="true" className="mr-1 inline-block h-2 w-0.5 align-middle bg-stone-500" />
              同期 SPY 上漲 baseline：{data.baseline.spy_up_pct.toFixed(1)}%
            </p>
          )}
        </div>
      )}
    </section>
  );
}
