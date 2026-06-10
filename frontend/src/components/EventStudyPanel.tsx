import { LoadingSpinner } from './LoadingSpinner';
import { Explainable, RuleTable } from './Explainable';
import { useEventStudy } from '../hooks/useHistory';
import type {
  EventStudyBucket,
  EventStudyHorizonStat,
} from '../api/history';

const ACTION_LABEL: Record<string, string> = {
  buy: '🟢 買入',
  reduce: '⚠ 減倉',
  hold: '✓ 持有',
  watch: '👀 觀望',
};

// Sample-size floor for treating the t-test as informative. The normal
// approximation we use is only well-behaved past ~30 observations; below
// that we render N<30 in muted text and suppress significance colour.
const MIN_N = 30;

// Two-sided significance thresholds. 5% is the standard cutoff for "found
// real alpha"; 1% is "very strong". Frontend uses both for visual hint
// (yellow vs green) so the user can see at a glance which buckets pass.
const ALPHA_005 = 0.05;
const ALPHA_001 = 0.01;

interface EventStudyPanelProps {
  symbol: string;
  days?: number;
}

export function EventStudyPanel({
  symbol,
  days,
}: EventStudyPanelProps): JSX.Element {
  const { data, isLoading, isError, refetch } = useEventStudy(
    symbol || null,
    days,
  );

  return (
    <div className="flex flex-col gap-3" data-testid="event-study-panel">
      <header className="flex flex-col gap-1">
        <h3 className="text-sm font-semibold text-stone-800">
          <Explainable
            title="Event Study 怎麼讀"
            explanation={
              <RuleTable
                preface="Event Study 是學術金融研究的標準工具。每個訊號當作一個「事件」,計算「事件後 N 個交易日,股票報酬 - SPY 報酬」的平均值(AR, abnormal return) 跟 t-test 顯著性。"
                rows={[
                  {
                    condition: 'AR (Abnormal Return)',
                    result:
                      '股票報酬扣掉 SPY 同期報酬 = 訊號帶來的「超額報酬」。',
                  },
                  {
                    condition: 'p-value < 0.05',
                    result:
                      '統計顯著 — 訊號真的捕捉到 alpha,不是隨機(綠色標示)。',
                  },
                  {
                    condition: 'p-value < 0.01',
                    result: '強顯著 — 拒絕「訊號 = 雜訊」假設(深綠標示)。',
                  },
                  {
                    condition: 'N < 30',
                    result:
                      '樣本太小,t-test 不可靠;數字仍顯示但不上色(灰字)。',
                  },
                  {
                    condition: 'AR 是負的且 p<0.05',
                    result:
                      '訊號方向錯了(例如「買入」訊號後股票實際 underperform)。對 reduce 來說 AR 負值反而代表「指標抓對下跌」。',
                  },
                ]}
                note="t-stat 是 mean / (stdev / sqrt(N))。我們用標準常態近似 t 分布(N≥30 時夠準);p 值是雙尾。"
              />
            }
          >
            Event Study (事件研究法)
          </Explainable>
        </h3>
        <p className="text-xs text-stone-500">
          每個訊號當作一個事件;統計 t+1 / t+5 / t+20 / t+60 個交易日的
          abnormal return (扣掉 SPY 同期報酬) + t-test 顯著性。
        </p>
      </header>

      {isLoading && (
        <div className="flex items-center gap-2 text-stone-500">
          <LoadingSpinner label="跑 event study…" />
          <span className="text-sm">分析中…</span>
        </div>
      )}
      {isError && (
        <div className="flex items-center justify-between rounded-md border border-rose-300 bg-rose-50 px-3 py-2 text-sm text-rose-700">
          <span>分析失敗。</span>
          <button type="button" onClick={() => void refetch()} className="underline">
            重試
          </button>
        </div>
      )}

      {data && Object.keys(data.by_action).length === 0 && (
        <p role="status" className="text-sm text-stone-500">
          所選範圍內沒有可分析的訊號。
        </p>
      )}

      {data && Object.keys(data.by_action).length > 0 && (
        <div className="overflow-hidden rounded-md border border-stone-200">
          <table className="w-full text-sm">
            <thead className="bg-stone-100 text-xs uppercase text-stone-500">
              <tr>
                <th scope="col" rowSpan={2} className="px-3 py-2 text-left align-middle">
                  動作
                </th>
                <th scope="col" rowSpan={2} className="px-3 py-2 text-right align-middle">
                  總事件
                </th>
                <th scope="col" colSpan={4} className="px-3 py-2 text-center">
                  Abnormal Return (% vs SPY)
                </th>
              </tr>
              <tr>
                {[1, 5, 20, 60].map((h) => (
                  <th
                    key={h}
                    scope="col"
                    className="px-2 py-1 text-right text-[11px] font-medium text-stone-500"
                  >
                    t+{h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-stone-200">
              {Object.entries(data.by_action).map(([action, bucket]) => (
                <EventStudyRow
                  key={action}
                  action={action}
                  bucket={bucket}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p className="text-[11px] text-stone-400">
        ⚠ 跟命中率同樣的 look-ahead bias 提醒:這些 AR 用「今天的指標公式」回算過去
        2 年,每次 INDICATOR_VERSION bump 都會重新計算。真實 forward-test 結果需要鎖死公式後等 6+ 個月。
      </p>
    </div>
  );
}

function EventStudyRow({
  action,
  bucket,
}: {
  action: string;
  bucket: EventStudyBucket;
}): JSX.Element {
  return (
    <tr className="bg-white">
      <th scope="row" className="px-3 py-2 text-left font-medium text-stone-800">
        {ACTION_LABEL[action] ?? action}
      </th>
      <td className="px-3 py-2 text-right font-mono text-stone-700">
        {bucket.n_events_total}
      </td>
      {bucket.horizons.map((h) => (
        <EventStudyCell key={h.horizon_days} stat={h} />
      ))}
    </tr>
  );
}

function EventStudyCell({ stat }: { stat: EventStudyHorizonStat }): JSX.Element {
  const insufficient = stat.n_events < MIN_N;
  const significant = !insufficient && stat.p_value < ALPHA_005;
  const strongly = !insufficient && stat.p_value < ALPHA_001;
  // Tone is driven by both significance + sign of the AR. Positive
  // significant = green (indicator captured upside / SELL bucket captured
  // downside). Negative significant = rose (indicator was systematically
  // wrong in that direction).
  const tone = insufficient
    ? 'text-stone-400'
    : strongly
      ? stat.avg_ar_pct >= 0
        ? 'text-emerald-700 font-bold'
        : 'text-rose-700 font-bold'
      : significant
        ? stat.avg_ar_pct >= 0
          ? 'text-emerald-600'
          : 'text-rose-600'
        : 'text-stone-700';
  return (
    <td className={`px-2 py-1.5 text-right font-mono ${tone}`}>
      <div className="text-xs">
        {stat.avg_ar_pct >= 0 ? '+' : ''}
        {stat.avg_ar_pct.toFixed(2)}%
      </div>
      <div className="text-[10px] text-stone-400">
        N={stat.n_events}
        {!insufficient && (
          <span className="ml-1">p={stat.p_value.toFixed(3)}</span>
        )}
      </div>
    </td>
  );
}
