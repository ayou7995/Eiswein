import { useState } from 'react';
import { LoadingSpinner } from '../components/LoadingSpinner';
import { PostureTimelineChart } from '../components/charts/PostureTimelineChart';
import {
  useMarketPostureHistory,
  usePostureAccuracy,
} from '../hooks/useHistory';
import { Explainable, RuleTable } from '../components/Explainable';
import { SymbolAccuracyRankingCard } from '../components/history/SymbolAccuracyRankingCard';
import {
  SIGNAL_ACCURACY_HORIZONS,
  type SignalAccuracyHorizon,
} from '../api/history';

// History page — Commit C rewrite. The per-ticker signal accuracy section
// moves to TickerDetailPage (one panel per symbol, accessed from the
// sidebar). HistoryPage now hosts:
//   1. Market posture timeline + posture accuracy (unchanged)
//   2. NEW: per-symbol hit-rate ranking, sharing the page's range selector
const DAYS_OPTIONS: readonly number[] = [30, 90, 365];

const POSTURE_LABEL_ZH: Record<string, string> = {
  offensive: '進攻',
  defensive: '防守',
};

const Z_95 = 1.96;
const MIN_SAMPLE_SIZE = 30;
function confidenceMargin(correct: number, total: number): number | null {
  if (total === 0) return null;
  const p = correct / total;
  const margin = Z_95 * Math.sqrt((p * (1 - p)) / total);
  return Math.min(100, margin * 100);
}

export function HistoryPage(): JSX.Element {
  // Single range source-of-truth for both the posture timeline AND the
  // symbol ranking card. Per Commit C plan: 30D / 90D / 365D.
  const [days, setDays] = useState<number>(90);

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-stone-900">
            歷史紀錄
          </h1>
          <p className="text-xs text-stone-500">
            市場態勢時間軸、市場態勢準確率，與各代碼命中率。
          </p>
        </div>
        <div
          role="radiogroup"
          aria-label="樣本範圍"
          className="inline-flex rounded-md border border-stone-300 bg-white p-0.5"
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
                className={`rounded px-3 py-1 text-xs font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500 ${
                  active
                    ? 'bg-sky-600 text-white'
                    : 'text-stone-700 hover:bg-stone-100'
                }`}
              >
                {d}D
              </button>
            );
          })}
        </div>
      </header>

      <MarketPostureSection days={days} />
      <SymbolAccuracyRankingCard days={days} />
    </div>
  );
}

interface MarketPostureSectionProps {
  days: number;
}

function MarketPostureSection({
  days,
}: MarketPostureSectionProps): JSX.Element {
  const [horizon, setHorizon] = useState<SignalAccuracyHorizon>(20);
  const historyQuery = useMarketPostureHistory(days);
  const accuracyQuery = usePostureAccuracy(horizon, days);
  const accuracyData = accuracyQuery.data;
  const historyData = historyQuery.data;

  return (
    <section
      aria-labelledby="history-posture-heading"
      className="flex flex-col gap-4 rounded-2xl border border-stone-200 bg-white p-6"
    >
      <header>
        <h2
          id="history-posture-heading"
          className="text-lg font-semibold text-stone-900"
        >
          市場態勢時間軸
        </h2>
        <p className="text-xs text-stone-500 mt-1">
          時間軸與下方準確率共享頁面頂端的樣本範圍。
        </p>
      </header>

      {historyQuery.isLoading && (
        <div className="flex items-center gap-2 text-stone-500">
          <LoadingSpinner label="載入市場態勢歷史…" />
          <span className="text-sm">載入中…</span>
        </div>
      )}
      {historyQuery.isError && (
        <div className="flex items-center justify-between rounded-md border border-rose-300 bg-rose-50 px-3 py-2 text-sm text-rose-700">
          <span>載入市場態勢歷史失敗。</span>
          <button
            type="button"
            onClick={() => void historyQuery.refetch()}
            className="underline"
          >
            重試
          </button>
        </div>
      )}
      {!historyQuery.isLoading && !historyQuery.isError && historyData && (
        <PostureTimelineChart data={historyData.data} />
      )}

      <div className="flex flex-col gap-3 border-t border-stone-200 pt-4">
        <header>
          <h3 className="text-base font-semibold">
            <Explainable
              title="市場態勢準確率"
              explanation={
                <RuleTable
                  preface="把上方的「市場態勢」當成方向訊號回測：進攻日期望 SPX 上漲、防守日期望 SPX 下跌、正常日無方向觀點不計入。命中規則跟個股訊號準確率對稱。"
                  rows={[
                    {
                      condition: '✨ 進攻',
                      result: 'N 日後 SPX 收盤 > 當日 → 算命中',
                    },
                    {
                      condition: '🛡 防守',
                      result: 'N 日後 SPX 收盤 < 當日 → 算命中',
                    },
                    { condition: '⚖ 正常', result: '不計入（沒方向觀點）' },
                  ]}
                  note="跟訊號準確率一樣是樣本內 backtest，看 vs SPY baseline + 95% CI 才能判斷有沒有真的預測力。"
                />
              }
            >
              市場態勢準確率
            </Explainable>
          </h3>
          <p className="text-xs text-stone-500 mt-1">
            以上方所選範圍內的市場態勢與 N 日後 SPY 方向比對。
          </p>
        </header>

        <div className="flex flex-wrap items-center gap-3">
          <span className="text-xs text-stone-500">命中 horizon</span>
          <div
            role="radiogroup"
            aria-label="態勢準確率時間範圍"
            className="inline-flex rounded-md border border-stone-300 bg-white p-0.5"
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
                  className={`rounded px-3 py-1 text-xs font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500 ${
                    active
                      ? 'bg-sky-600 text-white'
                      : 'text-stone-700 hover:bg-stone-100'
                  }`}
                >
                  {h} 日
                </button>
              );
            })}
          </div>
          <span className="text-xs text-stone-400">
            訊號發出後 N 個交易日比對 SPY 方向
          </span>
        </div>

        {accuracyQuery.isLoading && (
          <div className="flex items-center gap-2 text-stone-500">
            <LoadingSpinner label="載入態勢準確率…" />
            <span className="text-sm">載入中…</span>
          </div>
        )}
        {accuracyQuery.isError && (
          <div className="flex items-center justify-between rounded-md border border-rose-300 bg-rose-50 px-3 py-2 text-sm text-rose-700">
            <span>載入態勢準確率失敗。</span>
            <button
              type="button"
              onClick={() => void accuracyQuery.refetch()}
              className="underline"
            >
              重試
            </button>
          </div>
        )}

        {accuracyData && (
          <div className="flex flex-col gap-3">
            <AccuracyHeadline
              accuracyPct={accuracyData.accuracy_pct}
              correct={accuracyData.correct}
              total={accuracyData.total_signals}
              horizon={horizon}
              baselinePct={accuracyData.baseline.spy_up_pct}
              baselineTotal={accuracyData.baseline.total}
              sampleBreakdown={Object.entries(accuracyData.by_posture).map(
                ([posture, bucket]) => ({
                  label: POSTURE_LABEL_ZH[posture] ?? posture,
                  total: bucket.total,
                }),
              )}
              testId="posture-accuracy-headline"
            />
            {accuracyData.total_signals === 0 ? (
              <p role="status" className="text-sm text-stone-500">
                所選範圍內沒有方向性態勢訊號（全為「正常」），無法評估。
              </p>
            ) : (
              <div className="overflow-hidden rounded-md border border-stone-200">
                <table className="w-full text-sm">
                  <thead className="bg-stone-100 text-xs uppercase text-stone-500">
                    <tr>
                      <th scope="col" className="px-3 py-2 text-left">
                        態勢
                      </th>
                      <th scope="col" className="px-3 py-2 text-right">
                        天數
                      </th>
                      <th scope="col" className="px-3 py-2 text-right">
                        命中
                      </th>
                      <th scope="col" className="px-3 py-2 text-right">
                        準確率 ±95% CI
                      </th>
                      <th scope="col" className="px-3 py-2 text-right">
                        vs SPY baseline
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-stone-200">
                    {Object.entries(accuracyData.by_posture).map(
                      ([posture, bucket]) => {
                        const isDefensive = posture === 'defensive';
                        const isNormal = posture === 'normal';
                        // 3-class baseline: offensive vs SPY up,
                        // defensive vs SPY down, normal vs SPY flat.
                        const baselinePct = isDefensive
                          ? accuracyData.baseline.spy_down_pct
                          : isNormal
                            ? accuracyData.baseline.spy_flat_pct
                            : accuracyData.baseline.spy_up_pct;
                        const delta = bucket.accuracy_pct - baselinePct;
                        const margin = confidenceMargin(
                          bucket.correct,
                          bucket.total,
                        );
                        const ciClears =
                          margin !== null && Math.abs(delta) > margin;
                        const insufficient = bucket.total < MIN_SAMPLE_SIZE;
                        return (
                          <tr key={posture} className="bg-white">
                            <th
                              scope="row"
                              className="px-3 py-2 text-left font-medium text-stone-800"
                            >
                              {POSTURE_LABEL_ZH[posture] ?? posture}
                            </th>
                            <td className="px-3 py-2 text-right font-mono text-stone-700">
                              {bucket.total}
                            </td>
                            <td className="px-3 py-2 text-right font-mono text-stone-700">
                              {bucket.correct}
                            </td>
                            <td
                              className={`px-3 py-2 text-right font-mono ${
                                insufficient
                                  ? 'text-stone-400'
                                  : 'text-stone-800'
                              }`}
                            >
                              {insufficient ? (
                                <span className="text-xs">
                                  資料不足 (N&lt;{MIN_SAMPLE_SIZE})
                                </span>
                              ) : (
                                <>
                                  {bucket.accuracy_pct.toFixed(1)}%
                                  {margin !== null && (
                                    <span className="ml-1 text-[10px] text-stone-500">
                                      ±{margin.toFixed(1)}%
                                    </span>
                                  )}
                                </>
                              )}
                            </td>
                            <td
                              className={`px-3 py-2 text-right font-mono ${
                                insufficient
                                  ? 'text-stone-300'
                                  : ciClears && delta > 0
                                    ? 'text-emerald-700'
                                    : ciClears && delta < 0
                                      ? 'text-rose-700'
                                      : 'text-stone-500'
                              }`}
                            >
                              {insufficient ? (
                                '—'
                              ) : (
                                <>
                                  {delta >= 0 ? '+' : ''}
                                  {delta.toFixed(1)}%
                                </>
                              )}
                            </td>
                          </tr>
                        );
                      },
                    )}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </div>
    </section>
  );
}

interface SampleBreakdownEntry {
  label: string;
  total: number;
}

interface AccuracyHeadlineProps {
  accuracyPct: number;
  correct: number;
  total: number;
  horizon: number;
  baselinePct: number;
  baselineTotal: number;
  sampleBreakdown?: ReadonlyArray<SampleBreakdownEntry>;
  testId?: string;
}

function AccuracyHeadline({
  accuracyPct,
  correct,
  total,
  horizon,
  baselinePct,
  baselineTotal,
  sampleBreakdown,
  testId = 'accuracy-headline',
}: AccuracyHeadlineProps): JSX.Element {
  const margin = confidenceMargin(correct, total);
  const insufficient = total < MIN_SAMPLE_SIZE;
  const headlineTone = insufficient
    ? 'text-stone-400'
    : margin !== null && accuracyPct - margin >= baselinePct
      ? 'text-emerald-700'
      : 'text-stone-900';
  return (
    <div className="flex flex-col gap-2" data-testid={testId}>
      <div className="flex flex-wrap items-baseline gap-3">
        {insufficient ? (
          <span className={`text-2xl font-semibold ${headlineTone}`}>
            資料不足
          </span>
        ) : (
          <>
            <span className={`text-3xl font-semibold ${headlineTone}`}>
              {accuracyPct.toFixed(1)}%
            </span>
            {margin !== null && (
              <span className="text-sm text-stone-500">
                ±{margin.toFixed(1)}%
              </span>
            )}
          </>
        )}
        <span className="text-xs text-stone-500">
          {correct} / {total} 次命中（{horizon} 日;{insufficient
            ? `< ${MIN_SAMPLE_SIZE} 樣本不顯示百分比`
            : '95% CI'}）
        </span>
      </div>
      {sampleBreakdown && sampleBreakdown.length > 0 && (
        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-xs text-stone-500">
          <span className="text-stone-400">樣本拆分</span>
          {sampleBreakdown.map((s, idx) => (
            <span key={s.label}>
              <span className="text-stone-600">{s.label}</span>{' '}
              <span className="font-mono tabular-nums text-stone-700">
                {s.total}
              </span>
              {idx < sampleBreakdown.length - 1 && (
                <span className="ml-1 text-stone-300">·</span>
              )}
            </span>
          ))}
        </div>
      )}
      {baselineTotal > 0 && !insufficient && (
        <div className="flex flex-wrap items-baseline gap-2 text-xs text-stone-500">
          <span>同期 SPY 上漲 baseline</span>
          <span className="font-mono tabular-nums text-stone-700">
            {baselinePct.toFixed(1)}%
          </span>
          <span className="text-stone-400">
            （{baselineTotal} 個樣本日）
          </span>
        </div>
      )}
    </div>
  );
}
