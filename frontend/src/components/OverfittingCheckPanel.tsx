import { LoadingSpinner } from './LoadingSpinner';
import { Explainable, RuleTable } from './Explainable';
import {
  useRobustnessCheck,
  useTimeSplitValidation,
} from '../hooks/useHistory';
import type {
  RobustnessCheckResponse,
  TimeSplitResponse,
} from '../api/history';

interface OverfittingCheckPanelProps {
  symbol: string;
  days?: number;
}

// Threshold guidance for the "is this overfit?" verdict.
// Robustness range:
//   < 15 pp  → 穩定 (params not critical)
//   15-30 pp → 中等 (some sensitivity)
//   > 30 pp  → 敏感 (likely overfit to specific params)
// Time-split alpha delta:
//   |Δ| < 20 pp → 一致 (alpha persists out-of-sample)
//   20-50 pp    → 中等 (some drift, watch carefully)
//   > 50 pp     → 嚴重不一致 (overfit)
const ROBUSTNESS_STABLE_PP = 15;
const ROBUSTNESS_UNSTABLE_PP = 30;
const TIMESPLIT_CONSISTENT_PP = 20;
const TIMESPLIT_INCONSISTENT_PP = 50;

export function OverfittingCheckPanel({
  symbol,
  days,
}: OverfittingCheckPanelProps): JSX.Element {
  const robustness = useRobustnessCheck(symbol || null, days);
  const timeSplit = useTimeSplitValidation(symbol || null, days, 60);

  return (
    <div className="flex flex-col gap-4" data-testid="overfitting-check-panel">
      <header className="flex flex-col gap-1">
        <h3 className="text-sm font-semibold text-stone-800">
          <Explainable
            title="過擬合檢驗怎麼讀"
            explanation={
              <RuleTable
                preface="Backtest 數字本身不能告訴你「策略真的有 edge」還是「碰巧 fit 到過去資料」。這個 panel 跑兩個 overfitting 診斷:Robustness Check 換 50 種閾值看結果穩定度;Time-Split 把資料切兩半看 alpha 是否跨期保持。"
                rows={[
                  {
                    condition: 'Robustness range < 15 pp',
                    result:
                      '✅ 穩健 — 換閾值結果差不多,不是 fit 到特定參數',
                  },
                  {
                    condition: 'Robustness range 15-30 pp',
                    result: '⚠️ 中等敏感 — 結果會跟著閾值跑',
                  },
                  {
                    condition: 'Robustness range > 30 pp',
                    result:
                      '❌ 嚴重敏感 — 結果完全靠運氣選對閾值',
                  },
                  {
                    condition: 'Time-split |Δalpha| < 20 pp',
                    result: '✅ 一致 — alpha 跨期保持,可能真有 edge',
                  },
                  {
                    condition: 'Time-split |Δalpha| 20-50 pp',
                    result: '⚠️ 中度 drift — 觀察 forward-test',
                  },
                  {
                    condition: 'Time-split |Δalpha| > 50 pp',
                    result: '❌ 嚴重不一致 — 過去贏未來輸,典型 overfitting',
                  },
                ]}
                note="兩個都通過才算「值得 forward-test」。任何一個失敗都建議不要用真錢。"
              />
            }
          >
            過擬合檢驗 (Overfitting Check)
          </Explainable>
        </h3>
        <p className="text-xs text-stone-500">
          診斷 backtest 結果是否可信:Robustness 看閾值敏感度 · Time-Split 看跨期一致性。
        </p>
      </header>

      <RobustnessSection
        data={robustness.data ?? null}
        isLoading={robustness.isLoading}
        isError={robustness.isError}
        onRetry={() => void robustness.refetch()}
      />
      <TimeSplitSection
        data={timeSplit.data ?? null}
        isLoading={timeSplit.isLoading}
        isError={timeSplit.isError}
        onRetry={() => void timeSplit.refetch()}
      />
      <FinalVerdict
        robustness={robustness.data ?? null}
        timeSplit={timeSplit.data ?? null}
      />
    </div>
  );
}

function RobustnessSection({
  data,
  isLoading,
  isError,
  onRetry,
}: {
  data: RobustnessCheckResponse | null;
  isLoading: boolean;
  isError: boolean;
  onRetry: () => void;
}): JSX.Element {
  return (
    <section
      aria-label="Robustness Check"
      className="flex flex-col gap-2 rounded-md border border-stone-200 bg-white p-3"
    >
      <h4 className="text-sm font-medium text-stone-700">
        🎲 Robustness Check (50 種閾值組合)
      </h4>
      {isLoading && (
        <div className="flex items-center gap-2 text-stone-500">
          <LoadingSpinner label="跑 50 種閾值組合…" />
          <span className="text-sm">分析中…</span>
        </div>
      )}
      {isError && (
        <button
          type="button"
          onClick={onRetry}
          className="text-xs text-rose-700 underline"
        >
          載入失敗,重試
        </button>
      )}
      {data && data.n_runs > 0 && (
        <>
          <p className="text-[11px] text-stone-500">
            跑了 {data.n_runs} 種 (5 SL × 5 TP × 2 倉位) 組合,看 alpha 範圍:
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="bg-stone-100 text-[10px] uppercase tracking-wider text-stone-500">
                <tr>
                  <th className="px-2 py-1 text-left">指標</th>
                  <th className="px-2 py-1 text-right">中位數</th>
                  <th className="px-2 py-1 text-right">範圍 (min ↔ max)</th>
                  <th className="px-2 py-1 text-right">變動幅度</th>
                  <th className="px-2 py-1 text-right">σ</th>
                  <th className="px-2 py-1 text-left">判讀</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-stone-200">
                {(
                  [
                    ['total_return_pct', '策略總報酬'],
                    ['spy_alpha_pct', 'vs SPY alpha'],
                    ['stock_alpha_pct', 'vs 股票 B&H alpha'],
                    ['sharpe_ratio', 'Sharpe'],
                    ['max_drawdown_pct', 'Max DD'],
                  ] as const
                ).map(([metric, label]) => {
                  const stat = data.stats[metric];
                  if (!stat) return null;
                  const range = Math.abs(stat.range_value);
                  // Only colour-grade alpha-style metrics; Sharpe/MaxDD
                  // use raw values not pp.
                  const isAlpha =
                    metric === 'spy_alpha_pct' ||
                    metric === 'stock_alpha_pct' ||
                    metric === 'total_return_pct';
                  let verdict = '—';
                  let tone = 'text-stone-500';
                  if (isAlpha) {
                    if (range < ROBUSTNESS_STABLE_PP) {
                      verdict = '✅ 穩定';
                      tone = 'text-emerald-700';
                    } else if (range < ROBUSTNESS_UNSTABLE_PP) {
                      verdict = '⚠️ 中等敏感';
                      tone = 'text-amber-700';
                    } else {
                      verdict = '❌ 高敏感';
                      tone = 'text-rose-700';
                    }
                  } else {
                    // Sharpe / Max DD just informational
                    verdict = '參考用';
                  }
                  return (
                    <tr key={metric}>
                      <td className="px-2 py-1.5 font-medium text-stone-700">
                        {label}
                      </td>
                      <td className="px-2 py-1.5 text-right font-mono">
                        {stat.median >= 0 ? '+' : ''}
                        {stat.median.toFixed(2)}
                        {isAlpha ? '%' : ''}
                      </td>
                      <td className="px-2 py-1.5 text-right font-mono text-stone-500">
                        [{stat.min_value >= 0 ? '+' : ''}
                        {stat.min_value.toFixed(2)},{' '}
                        {stat.max_value >= 0 ? '+' : ''}
                        {stat.max_value.toFixed(2)}]
                      </td>
                      <td className={`px-2 py-1.5 text-right font-mono ${tone}`}>
                        Δ {range.toFixed(2)}
                        {isAlpha ? 'pp' : ''}
                      </td>
                      <td className="px-2 py-1.5 text-right font-mono text-stone-500">
                        {stat.stdev.toFixed(2)}
                      </td>
                      <td className={`px-2 py-1.5 text-[11px] ${tone}`}>
                        {verdict}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="text-[11px] text-stone-400">
            🎲 想法:同一檔股票如果 alpha 範圍很小(&lt; 15pp),意味著「不管你怎麼選 SL/TP/sizing,結果都差不多」 — 不是被特定參數 fit 出來的。
            如果範圍很大(&gt; 30pp),那 backtest 看到的高 alpha 可能只是 50 種裡剛好抽到的好運。
          </p>
        </>
      )}
      {data && data.n_runs === 0 && (
        <p className="text-sm text-stone-500">資料不足,無法跑 robustness check。</p>
      )}
    </section>
  );
}

function TimeSplitSection({
  data,
  isLoading,
  isError,
  onRetry,
}: {
  data: TimeSplitResponse | null;
  isLoading: boolean;
  isError: boolean;
  onRetry: () => void;
}): JSX.Element {
  return (
    <section
      aria-label="Time-Split Validation"
      className="flex flex-col gap-2 rounded-md border border-stone-200 bg-white p-3"
    >
      <h4 className="text-sm font-medium text-stone-700">
        🕒 Time-Split Validation (60% Train / 40% Test)
      </h4>
      {isLoading && (
        <div className="flex items-center gap-2 text-stone-500">
          <LoadingSpinner label="切分時段比對…" />
          <span className="text-sm">分析中…</span>
        </div>
      )}
      {isError && (
        <button
          type="button"
          onClick={onRetry}
          className="text-xs text-rose-700 underline"
        >
          載入失敗,重試
        </button>
      )}
      {data && data.train.n_snapshots > 0 && (
        <>
          <p className="text-[11px] text-stone-500">
            分割點:<span className="font-mono">{data.split_date}</span>{' '}
            (前 {data.split_pct}% 樣本為 train · 後 {100 - data.split_pct}% 為 test)
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="bg-stone-100 text-[10px] uppercase tracking-wider text-stone-500">
                <tr>
                  <th className="px-2 py-1 text-left">期間</th>
                  <th className="px-2 py-1 text-right">vs SPY alpha</th>
                  <th className="px-2 py-1 text-right">vs 股票 alpha</th>
                  <th className="px-2 py-1 text-right">Sharpe</th>
                  <th className="px-2 py-1 text-right">Max DD</th>
                  <th className="px-2 py-1 text-right">N 訊號</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-stone-200">
                <tr>
                  <td className="px-2 py-1.5 font-medium text-stone-700">
                    Train ({data.train.start_date} → {data.train.end_date})
                  </td>
                  <td className="px-2 py-1.5 text-right font-mono">
                    {data.train.spy_alpha_pct >= 0 ? '+' : ''}
                    {data.train.spy_alpha_pct.toFixed(2)}%
                  </td>
                  <td className="px-2 py-1.5 text-right font-mono">
                    {data.train.stock_alpha_pct >= 0 ? '+' : ''}
                    {data.train.stock_alpha_pct.toFixed(2)}%
                  </td>
                  <td className="px-2 py-1.5 text-right font-mono">
                    {data.train.sharpe_ratio.toFixed(2)}
                  </td>
                  <td className="px-2 py-1.5 text-right font-mono">
                    {data.train.max_drawdown_pct.toFixed(2)}%
                  </td>
                  <td className="px-2 py-1.5 text-right font-mono text-stone-500">
                    {data.train.n_snapshots}
                  </td>
                </tr>
                <tr className="bg-stone-50">
                  <td className="px-2 py-1.5 font-medium text-stone-700">
                    Test ({data.test.start_date} → {data.test.end_date})
                  </td>
                  <td className="px-2 py-1.5 text-right font-mono">
                    {data.test.spy_alpha_pct >= 0 ? '+' : ''}
                    {data.test.spy_alpha_pct.toFixed(2)}%
                  </td>
                  <td className="px-2 py-1.5 text-right font-mono">
                    {data.test.stock_alpha_pct >= 0 ? '+' : ''}
                    {data.test.stock_alpha_pct.toFixed(2)}%
                  </td>
                  <td className="px-2 py-1.5 text-right font-mono">
                    {data.test.sharpe_ratio.toFixed(2)}
                  </td>
                  <td className="px-2 py-1.5 text-right font-mono">
                    {data.test.max_drawdown_pct.toFixed(2)}%
                  </td>
                  <td className="px-2 py-1.5 text-right font-mono text-stone-500">
                    {data.test.n_snapshots}
                  </td>
                </tr>
                <tr className="font-semibold">
                  <td className="px-2 py-1.5 text-stone-700">
                    Δ (Test − Train)
                  </td>
                  <td
                    className={`px-2 py-1.5 text-right font-mono ${deltaToneClass(data.spy_alpha_delta)}`}
                  >
                    {data.spy_alpha_delta >= 0 ? '+' : ''}
                    {data.spy_alpha_delta.toFixed(2)}pp
                  </td>
                  <td
                    className={`px-2 py-1.5 text-right font-mono ${deltaToneClass(data.stock_alpha_delta)}`}
                  >
                    {data.stock_alpha_delta >= 0 ? '+' : ''}
                    {data.stock_alpha_delta.toFixed(2)}pp
                  </td>
                  <td className="px-2 py-1.5 text-right font-mono text-stone-500">
                    {data.sharpe_delta >= 0 ? '+' : ''}
                    {data.sharpe_delta.toFixed(2)}
                  </td>
                  <td colSpan={2}></td>
                </tr>
              </tbody>
            </table>
          </div>
          <p className="text-[11px] text-stone-400">
            🕒 想法:Train 跟 Test 的 alpha 應該差不多。如果差太多(&gt; 50pp),代表「過去 alpha 是 fit 出來的,未來不會持續」。Test alpha 比 train 還高也很可疑(可能 test 期間市場好做)。
          </p>
        </>
      )}
      {data && data.train.n_snapshots === 0 && (
        <p className="text-sm text-stone-500">
          樣本不足,無法切分(需要至少 30 個訊號)。
        </p>
      )}
    </section>
  );
}

function deltaToneClass(delta: number): string {
  const abs = Math.abs(delta);
  if (abs < TIMESPLIT_CONSISTENT_PP) return 'text-emerald-700';
  if (abs < TIMESPLIT_INCONSISTENT_PP) return 'text-amber-700';
  return 'text-rose-700';
}

function FinalVerdict({
  robustness,
  timeSplit,
}: {
  robustness: RobustnessCheckResponse | null;
  timeSplit: TimeSplitResponse | null;
}): JSX.Element | null {
  if (!robustness || !timeSplit) return null;
  if (timeSplit.train.n_snapshots === 0 || robustness.n_runs === 0) return null;

  const stockAlphaRange = Math.abs(
    robustness.stats.stock_alpha_pct?.range_value ?? 0,
  );
  const stockAlphaDelta = Math.abs(timeSplit.stock_alpha_delta);

  const robustOk = stockAlphaRange < ROBUSTNESS_UNSTABLE_PP;
  const timeSplitOk = stockAlphaDelta < TIMESPLIT_INCONSISTENT_PP;

  let verdict: string;
  let detail: string;
  let tone: string;

  if (robustOk && timeSplitOk) {
    if (
      stockAlphaRange < ROBUSTNESS_STABLE_PP &&
      stockAlphaDelta < TIMESPLIT_CONSISTENT_PP
    ) {
      verdict = '✅ 雙重通過 — 值得 forward-test';
      detail =
        '閾值穩健 + 跨期一致。下一步:凍結公式累積 3-6 個月真實 forward-tested 資料,如果還保持 → 可考慮小倉位試水。';
      tone = 'border-signal-green/40 bg-signal-green/10 text-signal-green';
    } else {
      verdict = '⚠️ 勉強通過 — 需要更多樣本';
      detail =
        '兩個檢驗都沒有大失敗但都有中度警訊。Backtest 結果參考用,還沒到能下真錢的程度。';
      tone = 'border-amber-400/40 bg-amber-50 text-amber-700';
    }
  } else if (!robustOk && !timeSplitOk) {
    verdict = '❌ 雙重失敗 — 嚴重 overfitting';
    detail =
      '閾值敏感 + 跨期不一致,backtest 結果幾乎肯定是運氣。不要用真錢操作這檔。';
    tone = 'border-signal-red/40 bg-signal-red/10 text-signal-red';
  } else if (!timeSplitOk) {
    verdict = '❌ 時間切分失敗 — overfitting 嫌疑';
    detail =
      'Train 跟 test alpha 差距太大。過去贏不代表未來贏,典型的 curve fitting。';
    tone = 'border-signal-red/40 bg-signal-red/10 text-signal-red';
  } else {
    verdict = '⚠️ 閾值敏感 — 結果不穩';
    detail =
      '不同參數組合結果差很多,backtest 數字運氣成分大。先別下真錢,或試別檔股票。';
    tone = 'border-amber-400/40 bg-amber-50 text-amber-700';
  }

  return (
    <section
      aria-label="綜合判讀"
      className={`flex flex-col gap-1 rounded-md border px-3 py-2 ${tone}`}
    >
      <h4 className="text-sm font-bold">{verdict}</h4>
      <p className="text-[11px] leading-relaxed text-stone-700">{detail}</p>
      <p className="text-[10px] text-stone-500">
        Robustness Δ(stock_alpha) = {stockAlphaRange.toFixed(2)}pp ·
        Time-Split Δ(stock_alpha) = {stockAlphaDelta.toFixed(2)}pp
      </p>
    </section>
  );
}
