import { useMemo, useState } from 'react';
import { LoadingSpinner } from './LoadingSpinner';
import { TickerSignalTimelineChart } from './charts/TickerSignalTimelineChart';
import { Explainable, RuleTable } from './Explainable';
import {
  SIGNAL_ACCURACY_HORIZONS,
  type SignalAccuracyHorizon,
  type TickerSignalPoint,
} from '../api/history';
import { useSignalAccuracy, useTickerSignals } from '../hooks/useHistory';

const TIMELINE_DAYS_OPTIONS: readonly number[] = [90, 180, 365];

const ACTION_LABEL: Record<string, string> = {
  strong_buy: '強力買入',
  buy: '買入',
  hold: '持有',
  watch: '觀望',
  reduce: '減倉',
  exit: '出場',
};

const ACTION_ORDER: ReadonlyArray<string> = [
  'strong_buy',
  'buy',
  'hold',
  'watch',
  'reduce',
  'exit',
];

const ACTION_TONE: Record<string, string> = {
  strong_buy: 'text-emerald-700 font-bold',
  buy: 'text-emerald-600',
  hold: 'text-stone-700',
  watch: 'text-stone-500',
  reduce: 'text-amber-700',
  exit: 'text-rose-700 font-bold',
};

const Z_95 = 1.96;

// Wilson 95% CI margin grows large for N<30 — we use the threshold both
// to suppress overall headline pct AND to grey out per-bucket rows so
// the operator isn't reading "60% ± 30%" as "60%".
export const MIN_SAMPLE_SIZE = 30;

function confidenceMargin(correct: number, total: number): number | null {
  if (total === 0) return null;
  const p = correct / total;
  const margin = Z_95 * Math.sqrt((p * (1 - p)) / total);
  return Math.min(100, margin * 100);
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
  baselineLabel?: string;
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
  baselineLabel = '同期 SPY 上漲 baseline',
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
          <span
            className={`text-2xl font-semibold ${headlineTone}`}
            data-testid="accuracy-insufficient"
          >
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
        <div
          className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-xs text-stone-500"
          data-testid="accuracy-sample-breakdown"
        >
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
          <span>{baselineLabel}</span>
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

interface SignalTimelineSectionProps {
  symbol: string;
  timelineDays: number;
  onTimelineDaysChange: (days: number) => void;
  data: ReadonlyArray<TickerSignalPoint> | null;
  isLoading: boolean;
  isError: boolean;
  onRetry: () => void;
}

function SignalTimelineSection({
  symbol,
  timelineDays,
  onTimelineDaysChange,
  data,
  isLoading,
  isError,
  onRetry,
}: SignalTimelineSectionProps): JSX.Element {
  return (
    <section
      aria-label={`${symbol} 訊號 vs 股價時間軸`}
      className="flex flex-col gap-2 rounded-md border border-stone-200 bg-stone-50 p-3"
    >
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-medium text-stone-800">訊號 vs 股價時間軸</h3>
        <div
          role="radiogroup"
          aria-label="時間軸區間"
          className="inline-flex rounded-md border border-stone-300 bg-white p-0.5"
        >
          {TIMELINE_DAYS_OPTIONS.map((d) => {
            const active = d === timelineDays;
            return (
              <button
                key={d}
                type="button"
                role="radio"
                aria-checked={active}
                onClick={() => onTimelineDaysChange(d)}
                className={`rounded px-2.5 py-1 text-xs font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500 ${
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
      {isLoading && (
        <div className="flex items-center gap-2 text-xs text-stone-500">
          <LoadingSpinner label="載入時間軸…" />
        </div>
      )}
      {isError && (
        <div className="flex items-center justify-between rounded-md border border-rose-300 bg-rose-50 px-3 py-2 text-xs text-rose-700">
          <span>載入時間軸失敗。</span>
          <button type="button" onClick={onRetry} className="underline">
            重試
          </button>
        </div>
      )}
      {!isLoading && !isError && data && data.length === 0 && (
        <p role="status" className="text-xs text-stone-500">
          所選區間沒有訊號資料。
        </p>
      )}
      {!isLoading && !isError && data && data.length > 0 && (
        <TickerSignalTimelineChart
          data={data}
          ariaLabel={`${symbol} 訊號 vs 股價時間軸`}
        />
      )}
    </section>
  );
}

interface SignalDistributionProps {
  data: ReadonlyArray<TickerSignalPoint>;
  windowDays: number;
}

function SignalDistribution({
  data,
  windowDays,
}: SignalDistributionProps): JSX.Element | null {
  const distribution = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const point of data) {
      counts[point.action] = (counts[point.action] ?? 0) + 1;
    }
    return counts;
  }, [data]);
  const total = data.length;
  if (total === 0) return null;
  return (
    <section
      aria-label="訊號分布"
      className="flex flex-col gap-2 rounded-md border border-stone-200 bg-stone-50 p-3"
    >
      <div className="flex items-baseline justify-between gap-2 text-xs">
        <span className="text-stone-500">
          過去 {windowDays} 天（{total} 個交易日）的訊號分布
        </span>
        <span className="text-stone-400">總計 {total}</span>
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
        {ACTION_ORDER.map((action) => {
          const count = distribution[action] ?? 0;
          const pct = total === 0 ? 0 : (count * 100) / total;
          const tone = ACTION_TONE[action] ?? 'text-stone-700';
          return (
            <div key={action} className="flex items-baseline gap-1.5">
              <span className={`font-medium ${tone}`}>
                {ACTION_LABEL[action] ?? action}
              </span>
              <span className="font-mono tabular-nums text-stone-800">{count}</span>
              <span className="text-stone-400">({pct.toFixed(0)}%)</span>
            </div>
          );
        })}
      </div>
    </section>
  );
}

interface SignalAccuracySectionProps {
  symbol: string;
}

// Per-ticker signal accuracy panel — chart + distribution + accuracy table +
// SPY baseline. Originally lived on HistoryPage; extracted in Commit C so
// TickerDetailPage can render it at the bottom (one operator-friendly
// scroll path) and HistoryPage can drop it in favour of the new ranking
// card. Window selector (90/180/365D) drives both the chart AND the
// stats so the user always reads a consistent slice.
export function SignalAccuracySection({
  symbol,
}: SignalAccuracySectionProps): JSX.Element {
  const [horizon, setHorizon] = useState<SignalAccuracyHorizon>(20);
  const [timelineDays, setTimelineDays] = useState<number>(180);
  const { data, isLoading, isError, refetch } = useSignalAccuracy(
    symbol || null,
    horizon,
    timelineDays,
  );
  const timelineQuery = useTickerSignals(symbol || null, timelineDays);

  return (
    <section
      aria-labelledby="ticker-accuracy-heading"
      className="flex flex-col gap-3 rounded-2xl border border-stone-200 bg-white p-6"
    >
      <header>
        <h2 id="ticker-accuracy-heading" className="text-lg font-semibold">
          <Explainable
            title="訊號準確率的限制"
            explanation={
              <RuleTable
                preface="這個數字告訴你「過去運算的建議動作 → N 日後收盤方向」的命中率。看起來簡單，但有幾個方法論限制必須先理解："
                rows={[
                  {
                    condition: '樣本內 backtest',
                    result:
                      '過去訊號是用「今天的公式」回算，每次 INDICATOR_VERSION bump 都重算過。look-ahead bias 存在。',
                  },
                  {
                    condition: '無因果，只比方向',
                    result:
                      '「持有 + 漲」算對，但「持有」其實沒有 directional 觀點 — 故 by_action 才是核心。',
                  },
                  {
                    condition: '需要 baseline',
                    result:
                      '同期 SPY 漲跌比例就是「always-buy」baseline。系統命中率沒贏 baseline = 跟隨市場 beta 而非真有預測力。',
                  },
                  {
                    condition: '樣本要夠大',
                    result:
                      'N < 30 信賴區間太寬，數字不可信；N ≥ 100 才適合相對比較。',
                  },
                ]}
                note="真正的 forward-test 要從「鎖死 INDICATOR_VERSION」開始累積，至少 6 個月後再評估。"
              />
            }
          >
            個股訊號準確率
          </Explainable>
        </h2>
        <p className="text-xs text-stone-500 mt-1" data-testid="accuracy-disclaimer">
          此統計基於歷史計算，僅供參考。以過去運算的建議動作與 N 日後收盤方向比對。
        </p>
      </header>

      {isLoading && (
        <div className="flex items-center gap-2 text-stone-500">
          <LoadingSpinner label="載入準確率…" />
          <span className="text-sm">載入中…</span>
        </div>
      )}
      {isError && (
        <div className="flex items-center justify-between rounded-md border border-rose-300 bg-rose-50 px-3 py-2 text-sm text-rose-700">
          <span>載入準確率失敗。</span>
          <button
            type="button"
            onClick={() => void refetch()}
            className="underline"
          >
            重試
          </button>
        </div>
      )}

      {data && (
        <div className="flex flex-col gap-3">
          <SignalTimelineSection
            symbol={symbol}
            timelineDays={timelineDays}
            onTimelineDaysChange={setTimelineDays}
            data={timelineQuery.data?.data ?? null}
            isLoading={timelineQuery.isLoading}
            isError={timelineQuery.isError}
            onRetry={() => void timelineQuery.refetch()}
          />
          <SignalDistribution
            data={timelineQuery.data?.data ?? []}
            windowDays={timelineDays}
          />
          <div className="flex flex-wrap items-center gap-3 border-t border-stone-200 pt-3">
            <span className="text-xs text-stone-500">命中 horizon</span>
            <div
              role="radiogroup"
              aria-label="準確率時間範圍"
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
              訊號發出後 N 個交易日比對股價方向
            </span>
          </div>
          <AccuracyHeadline
            accuracyPct={data.accuracy_pct}
            correct={data.correct}
            total={data.total_signals}
            horizon={horizon}
            baselinePct={data.baseline.spy_up_pct}
            baselineTotal={data.baseline.total}
            sampleBreakdown={Object.entries(data.by_action).map(
              ([action, bucket]) => ({
                label: ACTION_LABEL[action] ?? action,
                total: bucket.total,
              }),
            )}
          />
          {data.total_signals === 0 ? (
            <p role="status" className="text-sm text-stone-500">
              尚無足夠訊號可評估。
            </p>
          ) : (
            <div className="overflow-hidden rounded-md border border-stone-200">
              <table className="w-full text-sm">
                <thead className="bg-stone-100 text-xs uppercase text-stone-500">
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
                      準確率 ±95% CI
                    </th>
                    <th scope="col" className="px-3 py-2 text-right">
                      vs SPY 命中
                    </th>
                    <th scope="col" className="px-3 py-2 text-right">
                      平均 % 報酬
                    </th>
                    <th scope="col" className="px-3 py-2 text-right">
                      vs SPY 報酬
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-stone-200">
                  {Object.entries(data.by_action).map(([action, bucket]) => {
                    const isSellSide = action === 'reduce' || action === 'exit';
                    const isFlatSide = action === 'hold' || action === 'watch';
                    // 3-class baseline matched to the action's expected
                    // direction: BUY vs SPY up, SELL vs SPY down, HOLD/WATCH
                    // vs SPY flat. The class-matched baseline gives a fair
                    // "could you have guessed this just from SPY drift"
                    // comparison per bucket.
                    const baselinePct = isSellSide
                      ? data.baseline.spy_down_pct
                      : isFlatSide
                        ? data.baseline.spy_flat_pct
                        : data.baseline.spy_up_pct;
                    const delta = bucket.accuracy_pct - baselinePct;
                    const margin = confidenceMargin(bucket.correct, bucket.total);
                    const ciClears =
                      margin !== null && Math.abs(delta) > margin;
                    const insufficient = bucket.total < MIN_SAMPLE_SIZE;
                    return (
                      <tr key={action} className="bg-white">
                        <th
                          scope="row"
                          className="px-3 py-2 text-left font-medium text-stone-800"
                        >
                          {ACTION_LABEL[action] ?? action}
                        </th>
                        <td className="px-3 py-2 text-right font-mono text-stone-700">
                          {bucket.total}
                        </td>
                        <td className="px-3 py-2 text-right font-mono text-stone-700">
                          {bucket.correct}
                        </td>
                        <td
                          className={`px-3 py-2 text-right font-mono ${
                            insufficient ? 'text-stone-400' : 'text-stone-800'
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
                        <td
                          className={`px-3 py-2 text-right font-mono ${
                            insufficient
                              ? 'text-stone-400'
                              : bucket.avg_return_pct > 0
                                ? 'text-emerald-700'
                                : bucket.avg_return_pct < 0
                                  ? 'text-rose-700'
                                  : 'text-stone-500'
                          }`}
                        >
                          {insufficient
                            ? '—'
                            : `${bucket.avg_return_pct >= 0 ? '+' : ''}${bucket.avg_return_pct.toFixed(2)}%`}
                        </td>
                        <td
                          className={`px-3 py-2 text-right font-mono ${
                            insufficient
                              ? 'text-stone-300'
                              : bucket.delta_vs_baseline > 0
                                ? 'text-emerald-700'
                                : bucket.delta_vs_baseline < 0
                                  ? 'text-rose-700'
                                  : 'text-stone-500'
                          }`}
                        >
                          {insufficient
                            ? '—'
                            : `${bucket.delta_vs_baseline >= 0 ? '+' : ''}${bucket.delta_vs_baseline.toFixed(2)}%`}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
