import { useMemo, useState } from 'react';
import { LoadingSpinner } from '../components/LoadingSpinner';
import { PostureTimelineChart } from '../components/charts/PostureTimelineChart';
import { TickerSignalTimelineChart } from '../components/charts/TickerSignalTimelineChart';
import {
  useMarketPostureHistory,
  useSignalAccuracy,
  useTickerSignals,
} from '../hooks/useHistory';
import { useWatchlist } from '../hooks/useWatchlist';
import { Explainable, RuleTable } from '../components/Explainable';
import {
  SIGNAL_ACCURACY_HORIZONS,
  type SignalAccuracyHorizon,
} from '../api/history';

const TIMELINE_DAYS_OPTIONS: readonly number[] = [90, 180, 365];

const DAYS_OPTIONS: readonly number[] = [30, 90, 180, 365];

const ACTION_LABEL: Record<string, string> = {
  strong_buy: '強力買入',
  buy: '買入',
  hold: '持有',
  watch: '觀望',
  reduce: '減倉',
  exit: '出場',
};

// Display order for the signal distribution row: highest-conviction
// buy on the left, downgrading rightward to highest-conviction sell.
// Using a fixed ordering rather than a sort by count keeps the visual
// stable across symbols / horizons.
const ACTION_ORDER: ReadonlyArray<string> = [
  'strong_buy',
  'buy',
  'hold',
  'watch',
  'reduce',
  'exit',
];

const ACTION_TONE: Record<string, string> = {
  strong_buy: 'text-signal-green font-bold',
  buy: 'text-signal-green',
  hold: 'text-slate-300',
  watch: 'text-slate-400',
  reduce: 'text-signal-yellow',
  exit: 'text-signal-red font-bold',
};

// Replaces the old sampleSizeLabel amber/gray warnings. With the
// window-aware accuracy filter most per-action buckets land below 30
// samples, so a constant "樣本不足" tag fires alarm fatigue. A binomial
// 95 % confidence interval gives the user the same information
// quantitatively — N=44 hits 17 reads "38.6 % ±14.4 %", N=3 hits 1
// reads "33.3 % ±53.3 %" — letting them weigh certainty themselves.
const Z_95 = 1.96;

function confidenceMargin(correct: number, total: number): number | null {
  // Standard 95 % normal-approx interval on a binomial proportion.
  // Returns the half-width as a percentage (0-100). Wilson-score is
  // more accurate at the extremes but harder to read at a glance, and
  // the user's mental model here is the symmetric ± around the mean.
  if (total === 0) return null;
  const p = correct / total;
  const margin = Z_95 * Math.sqrt((p * (1 - p)) / total);
  return Math.min(100, margin * 100);
}

interface SignalTimelineSectionProps {
  symbol: string;
  timelineDays: number;
  onTimelineDaysChange: (days: number) => void;
  data: ReadonlyArray<import('../api/history').TickerSignalPoint> | null;
  isLoading: boolean;
  isError: boolean;
  onRetry: () => void;
}

// Visual sanity-check: did the price actually do what the action
// implied? A 減倉 marker right before a price climb is a miss; a
// 強買 marker right before a rally validates the system. Far more
// informative than a single hit-rate percentage.
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
      className="flex flex-col gap-2 rounded-md border border-slate-800 bg-slate-950/40 p-3"
    >
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-medium text-slate-200">訊號 vs 股價時間軸</h3>
        <div
          role="radiogroup"
          aria-label="時間軸區間"
          className="inline-flex rounded-md border border-slate-700 bg-slate-900/40 p-0.5"
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
                className={`rounded px-2.5 py-1 text-xs font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400 ${
                  active
                    ? 'bg-sky-600 text-white'
                    : 'text-slate-300 hover:bg-slate-800 hover:text-white'
                }`}
              >
                {d}D
              </button>
            );
          })}
        </div>
      </header>
      {isLoading && (
        <div className="flex items-center gap-2 text-xs text-slate-400">
          <LoadingSpinner label="載入時間軸…" />
        </div>
      )}
      {isError && (
        <div className="flex items-center justify-between rounded-md border border-signal-red/40 bg-signal-red/10 px-3 py-2 text-xs text-signal-red">
          <span>載入時間軸失敗。</span>
          <button
            type="button"
            onClick={onRetry}
            className="underline hover:text-signal-red"
          >
            重試
          </button>
        </div>
      )}
      {!isLoading && !isError && data && data.length === 0 && (
        <p role="status" className="text-xs text-slate-400">
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
  // Derived from the same TickerSignalPoint[] the chart consumes so the
  // counts always match the timeline window the user is looking at —
  // 90D / 180D / 365D toggles flip both views in sync. Earlier we read
  // a backend `signal_distribution` field that always counted ALL
  // history; switching windows surfaced a confusing split (e.g. "圖
  // 只有 2 個買，但分布說有 3 個" because the third was outside the
  // window).
  data: ReadonlyArray<import('../api/history').TickerSignalPoint>;
  windowDays: number;
}

function SignalDistribution({ data, windowDays }: SignalDistributionProps): JSX.Element | null {
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
      className="flex flex-col gap-2 rounded-md border border-slate-800 bg-slate-950/40 p-3"
    >
      <div className="flex items-baseline justify-between gap-2 text-xs">
        <span className="text-slate-400">
          過去 {windowDays} 天（{total} 個交易日）的訊號分布
        </span>
        <span className="text-slate-500">總計 {total}</span>
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
        {ACTION_ORDER.map((action) => {
          const count = distribution[action] ?? 0;
          const pct = total === 0 ? 0 : (count * 100) / total;
          const tone = ACTION_TONE[action] ?? 'text-slate-300';
          return (
            <div key={action} className="flex items-baseline gap-1.5">
              <span className={`font-medium ${tone}`}>{ACTION_LABEL[action] ?? action}</span>
              <span className="font-mono tabular-nums text-slate-200">{count}</span>
              <span className="text-slate-500">({pct.toFixed(0)}%)</span>
            </div>
          );
        })}
      </div>
    </section>
  );
}

interface AccuracyHeadlineProps {
  accuracyPct: number;
  correct: number;
  total: number;
  horizon: number;
  baselinePct: number;
  baselineTotal: number;
}

function AccuracyHeadline({
  accuracyPct,
  correct,
  total,
  horizon,
  baselinePct,
  baselineTotal,
}: AccuracyHeadlineProps): JSX.Element {
  const margin = confidenceMargin(correct, total);
  // Tone reflects directional confidence vs SPY baseline only when the
  // CI actually clears the baseline gap — a "winning" 38 % over 5 trades
  // with ±43 % CI is statistically a coin flip and shouldn't be tinted
  // green.
  const headlineTone =
    margin !== null && accuracyPct - margin >= baselinePct
      ? 'text-signal-green'
      : 'text-slate-100';
  return (
    <div className="flex flex-col gap-2" data-testid="accuracy-headline">
      <div className="flex flex-wrap items-baseline gap-3">
        <span className={`text-3xl font-semibold ${headlineTone}`}>
          {accuracyPct.toFixed(1)}%
        </span>
        {margin !== null && (
          <span className="text-sm text-slate-400">±{margin.toFixed(1)}%</span>
        )}
        <span className="text-xs text-slate-400">
          {correct} / {total} 次命中（{horizon} 日）
        </span>
      </div>
      {baselineTotal > 0 && (
        <div className="flex flex-wrap items-baseline gap-2 text-xs text-slate-400">
          <span>同期 SPY 上漲 baseline</span>
          <span className="font-mono tabular-nums text-slate-200">
            {baselinePct.toFixed(1)}%
          </span>
          <span className="text-slate-500">
            （{baselineTotal} 個樣本日 — 「always-buy SPY」會對的比例）
          </span>
        </div>
      )}
    </div>
  );
}

export function HistoryPage(): JSX.Element {
  return (
    <div className="flex flex-col gap-6">
      <header>
        <h1 className="text-2xl font-semibold">歷史紀錄</h1>
        <p className="text-xs text-slate-500">
          市場態勢時間軸與訊號準確率。
        </p>
      </header>

      <MarketPostureSection />
      <SignalAccuracySection />
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
  // Exclude system symbols (SPY) — SPY is the SPX proxy, so its
  // relative-strength indicator is always NEUTRAL against itself and
  // the per-ticker action is permanently "watch". That produces 0/0
  // on the accuracy query, which is confusing. Hide from the dropdown.
  const symbols = useMemo(
    () =>
      (watchlist.data?.data ?? [])
        .filter((w) => !w.isSystem)
        .map((w) => w.symbol)
        .slice()
        .sort((a, b) => a.localeCompare(b)),
    [watchlist.data],
  );
  const [symbol, setSymbol] = useState<string>('');
  // 20 trading days ≈ 1 month, the O'Neil/Sherry-style core window the
  // 12 indicators are tuned for. 5 is kept for short-term curiosity but
  // visually de-emphasised in the disclaimer popover.
  const [horizon, setHorizon] = useState<SignalAccuracyHorizon>(20);

  const effectiveSymbol = symbol || symbols[0] || '';
  // The chart-range selector (90 / 180 / 365D) is the single source of
  // truth for "what window am I looking at?" — it drives BOTH the
  // signal-vs-price chart and the accuracy / distribution stats below.
  // Earlier the chart range only filtered the chart while accuracy ran
  // over the full snapshot history, which made distribution and command
  // table describe different windows ("圖只有 2 個買，但分布說有 3 個").
  const [timelineDays, setTimelineDays] = useState<number>(180);
  const { data, isLoading, isError, refetch } = useSignalAccuracy(
    effectiveSymbol || null,
    horizon,
    timelineDays,
  );
  const timelineQuery = useTickerSignals(effectiveSymbol || null, timelineDays);

  return (
    <section
      aria-labelledby="history-accuracy-heading"
      className="flex flex-col gap-3 rounded-lg border border-slate-800 bg-slate-900/60 p-4"
    >
      <header>
        <h2 id="history-accuracy-heading" className="text-lg font-semibold">
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
                    result: '「持有 + 漲」算對，但「持有」其實沒有 directional 觀點 — 故 by_action 才是核心。',
                  },
                  {
                    condition: '需要 baseline',
                    result: '同期 SPY 漲跌比例就是「always-buy」baseline。系統命中率沒贏 baseline = 跟隨市場 beta 而非真有預測力。',
                  },
                  {
                    condition: '樣本要夠大',
                    result: 'N < 30 信賴區間太寬，數字不可信；N ≥ 100 才適合相對比較。',
                  },
                ]}
                note="真正的 forward-test 要從「鎖死 INDICATOR_VERSION」開始累積，至少 6 個月後再評估。"
              />
            }
          >
            訊號準確率
          </Explainable>
        </h2>
        <p className="text-xs text-slate-400 mt-1" data-testid="accuracy-disclaimer">
          此統計基於歷史計算，僅供參考。
        </p>
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
          <SignalTimelineSection
            symbol={effectiveSymbol}
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
          {/* Horizon selector now sits adjacent to the accuracy table
              it controls — the chart-window selector lives above the
              chart, the horizon selector lives above the by-action
              table. Two selectors, two domains, each next to its own
              consequence. */}
          <div className="flex flex-wrap items-center gap-3 border-t border-slate-800 pt-3">
            <span className="text-xs text-slate-400">命中 horizon</span>
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
                      active
                        ? 'bg-sky-600 text-white'
                        : 'text-slate-300 hover:bg-slate-800 hover:text-white'
                    }`}
                  >
                    {h} 日
                  </button>
                );
              })}
            </div>
            <span className="text-xs text-slate-500">
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
          />
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
                      準確率 ±95% CI
                    </th>
                    <th scope="col" className="px-3 py-2 text-right">
                      vs SPY baseline
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800">
                  {Object.entries(data.by_action).map(([action, bucket]) => {
                    // For sell-side actions the baseline flips: a sell call
                    // is "right" when SPY went DOWN, so the bar to clear is
                    // (100 − spy_up_pct) rather than spy_up_pct itself.
                    const isSellSide = action === 'reduce' || action === 'exit';
                    const baselinePct = isSellSide
                      ? 100 - data.baseline.spy_up_pct
                      : data.baseline.spy_up_pct;
                    const delta = bucket.accuracy_pct - baselinePct;
                    const margin = confidenceMargin(bucket.correct, bucket.total);
                    // Only call the delta meaningful when the CI clears
                    // the gap — a +5 % delta with ±25 % CI is noise, not
                    // a real win.
                    const ciClears = margin !== null && Math.abs(delta) > margin;
                    return (
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
                          {margin !== null && (
                            <span className="ml-1 text-[10px] text-slate-500">
                              ±{margin.toFixed(1)}%
                            </span>
                          )}
                        </td>
                        <td
                          className={`px-3 py-2 text-right font-mono ${
                            ciClears && delta > 0
                              ? 'text-signal-green'
                              : ciClears && delta < 0
                                ? 'text-signal-red'
                                : 'text-slate-400'
                          }`}
                        >
                          {delta >= 0 ? '+' : ''}
                          {delta.toFixed(1)}%
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

