import { useMemo, useState } from 'react';
import { LoadingSpinner } from '../components/LoadingSpinner';
import { PostureTimelineChart } from '../components/charts/PostureTimelineChart';
import { useMarketPostureHistory, useSignalAccuracy } from '../hooks/useHistory';
import { useWatchlist } from '../hooks/useWatchlist';
import { Explainable, RuleTable } from '../components/Explainable';
import {
  SIGNAL_ACCURACY_HORIZONS,
  type SignalAccuracyHorizon,
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

// Sample-size thresholds for the per-action and overall accuracy displays.
// Below SAMPLE_LOW (~30) the binomial confidence interval is too wide to
// trust the point estimate at all; SAMPLE_MID (~100) approaches "good
// enough for relative comparison". These match common rule-of-thumb in
// statistics and the staff-review guidance.
const SAMPLE_LOW = 30;
const SAMPLE_MID = 100;

function sampleSizeLabel(n: number): { label: string; tone: string } | null {
  if (n === 0) return null;
  if (n < SAMPLE_LOW)
    return { label: `樣本不足（${n} < ${SAMPLE_LOW}）`, tone: 'text-slate-500' };
  if (n < SAMPLE_MID)
    return { label: `樣本偏少（${n} < ${SAMPLE_MID}）`, tone: 'text-amber-400' };
  return null;
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
  const sample = sampleSizeLabel(total);
  // Headline number gets tinted by sample-size confidence, not by
  // whether the user is "winning" — a 90 % accuracy on 4 trades is
  // still noise, not skill.
  const headlineTone = sample
    ? sample.tone
    : accuracyPct >= baselinePct
      ? 'text-signal-green'
      : 'text-slate-100';
  return (
    <div className="flex flex-col gap-2" data-testid="accuracy-headline">
      <div className="flex flex-wrap items-baseline gap-3">
        <span className={`text-3xl font-semibold ${headlineTone}`}>
          {accuracyPct.toFixed(1)}%
        </span>
        <span className="text-xs text-slate-400">
          {correct} / {total} 次命中（{horizon} 日）
        </span>
        {sample && <span className={`text-xs ${sample.tone}`}>{sample.label}</span>}
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
                      準確率
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
                    const sample = sampleSizeLabel(bucket.total);
                    return (
                      <tr key={action} className="bg-slate-950/40">
                        <th scope="row" className="px-3 py-2 text-left font-medium text-slate-200">
                          {ACTION_LABEL[action] ?? action}
                        </th>
                        <td className="px-3 py-2 text-right font-mono text-slate-300">
                          {bucket.total}
                          {sample && (
                            <span className={`ml-1 text-[10px] ${sample.tone}`}>
                              {sample.label}
                            </span>
                          )}
                        </td>
                        <td className="px-3 py-2 text-right font-mono text-slate-300">
                          {bucket.correct}
                        </td>
                        <td className="px-3 py-2 text-right font-mono text-slate-200">
                          {bucket.accuracy_pct.toFixed(1)}%
                        </td>
                        <td
                          className={`px-3 py-2 text-right font-mono ${
                            delta > 5
                              ? 'text-signal-green'
                              : delta < -5
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

