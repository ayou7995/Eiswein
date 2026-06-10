import { useMemo, useState } from 'react';
import { LoadingSpinner } from './LoadingSpinner';
import { Explainable, RuleTable } from './Explainable';
import { IndicatorMultiLine } from './charts/IndicatorMultiLine';
import { usePnlSimulation } from '../hooks/useHistory';
import type { PnlSummary, PnlTrade } from '../api/history';

interface PnlSimulationPanelProps {
  symbol: string;
  days?: number;
}

const ACTION_LABEL: Record<string, string> = {
  strong_buy: '🟢🟢 強買',
  buy: '🟢 買入',
  hold: '✓ 持有',
  watch: '👀 觀望',
  reduce: '⚠ 減倉',
  exit: '🔴🔴 出場',
};

const EXIT_REASON_LABEL: Record<string, string> = {
  signal_exit: '訊號出場',
  end_of_window: '期末平倉',
};

export function PnlSimulationPanel({
  symbol,
  days,
}: PnlSimulationPanelProps): JSX.Element {
  const [showTrades, setShowTrades] = useState(false);
  const { data, isLoading, isError, refetch } = usePnlSimulation(
    symbol || null,
    days,
  );

  return (
    <div className="flex flex-col gap-3" data-testid="pnl-simulation-panel">
      <header className="flex flex-col gap-1">
        <h3 className="text-sm font-semibold text-stone-800">
          <Explainable
            title="PnL Simulation 怎麼讀"
            explanation={
              <RuleTable
                preface="模擬「假設我從頭照訊號操作 N 天,$10,000 起始資金,N 天後變多少錢?」交易規則 (v2):buy / strong_buy / hold + 沒部位 → 全倉進場(hold 也算進場是因為「持有」訊號隱含「現在應該在場」);reduce/exit + 有部位 → 全部平倉;watch → 不變動(觀望 = 維持現狀)。沒有止損機制。"
                rows={[
                  {
                    condition: 'vs SPY Alpha',
                    result:
                      '策略總報酬 − SPY buy-and-hold 報酬。正值 = 跑贏大盤;負值 = 不如直接買 SPY ETF 放著。',
                  },
                  {
                    condition: 'vs 股票 B&H Alpha',
                    result:
                      '策略總報酬 − 直接買這檔 buy-and-hold。正值 = 訊號真的幫了你;負值 = 直接買股票放著比較好,訊號反而扣分。',
                  },
                  {
                    condition: 'Sharpe Ratio',
                    result:
                      '風險調整後報酬,年化。> 1 = 好,> 2 = 很好。SPY 長期約 0.7-1.0。',
                  },
                  {
                    condition: 'Max Drawdown',
                    result:
                      '帳戶從歷史最高點跌到最低點的百分比。-20% 以內可接受;-40% 以上心臟要強。',
                  },
                  {
                    condition: 'Win Rate',
                    result:
                      '單筆獲利的交易 ÷ 總交易次數。50%+ 算可以,但要搭配 avg win / avg loss 一起看。',
                  },
                  {
                    condition: 'Avg Win / Avg Loss',
                    result:
                      '平均賺多少 vs 平均賠多少。Win/Loss ratio > 1.5 + Win Rate > 40% 通常能正期望值。',
                  },
                  {
                    condition: 'In-Market %',
                    result:
                      '有持倉的天數比例。低 = 大部分時間在 cash(機會成本高);高 = 滿倉(漲跟跌都跟著)。',
                  },
                ]}
                note="同樣的 look-ahead bias:用今天的指標公式回算過去。真實 forward-test 要鎖死公式後等 6+ 個月。"
              />
            }
          >
            PnL Simulation (假交易回測)
          </Explainable>
        </h3>
        <p className="text-xs text-stone-500">
          假設你從 $10,000 起始,看到訊號就照做。策略 vs SPY buy-and-hold 比較。
        </p>
      </header>

      {isLoading && (
        <div className="flex items-center gap-2 text-stone-500">
          <LoadingSpinner label="跑 PnL 模擬…" />
          <span className="text-sm">模擬中…</span>
        </div>
      )}
      {isError && (
        <div className="flex items-center justify-between rounded-md border border-rose-300 bg-rose-50 px-3 py-2 text-sm text-rose-700">
          <span>模擬失敗。</span>
          <button
            type="button"
            onClick={() => void refetch()}
            className="underline"
          >
            重試
          </button>
        </div>
      )}

      {data && data.summary.n_trades === 0 && data.daily_values.length === 0 && (
        <p role="status" className="text-sm text-stone-500">
          所選範圍內沒有可模擬的訊號。
        </p>
      )}

      {data && data.daily_values.length > 0 && (
        <>
          <SummaryCard summary={data.summary} />
          <EquityCurve data={data.daily_values} />
          <TradesSection
            trades={data.trades}
            isOpen={showTrades}
            onToggle={() => setShowTrades((v) => !v)}
          />
        </>
      )}

      <p className="text-[11px] text-stone-400">
        ⚠ Look-ahead bias 提醒:策略用「今天的指標公式」回算過去 2 年,每次
        INDICATOR_VERSION bump 都會重算。沒有 slippage、手續費、稅務模型;沒有止損機制。真實
        forward-test 結果需要鎖死公式後等 6+ 個月才能比對。
      </p>
    </div>
  );
}

function SummaryCard({ summary }: { summary: PnlSummary }): JSX.Element {
  const spyAlphaPositive = summary.spy_alpha_pct >= 0;
  const stockAlphaPositive = summary.stock_alpha_pct >= 0;
  const drawdownSevere = summary.max_drawdown_pct <= -30;
  const sharpeGood = summary.sharpe_ratio >= 1;
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
      <Metric
        label="策略總報酬"
        primaryValue={`${summary.total_return_pct >= 0 ? '+' : ''}${summary.total_return_pct.toFixed(2)}%`}
        secondaryValue={`$${summary.starting_capital.toLocaleString()} → $${summary.final_value.toLocaleString()}`}
        tone={summary.total_return_pct > 0 ? 'green' : summary.total_return_pct < 0 ? 'red' : 'neutral'}
      />
      <Metric
        label="vs SPY"
        primaryValue={`${spyAlphaPositive ? '+' : ''}${summary.spy_alpha_pct.toFixed(2)}%`}
        secondaryValue={`SPY 同期 ${summary.spy_total_return_pct >= 0 ? '+' : ''}${summary.spy_total_return_pct.toFixed(2)}%`}
        tone={spyAlphaPositive ? 'green' : 'red'}
      />
      <Metric
        label="vs 股票 B&H"
        primaryValue={`${stockAlphaPositive ? '+' : ''}${summary.stock_alpha_pct.toFixed(2)}%`}
        secondaryValue={`直接買股票 ${summary.stock_total_return_pct >= 0 ? '+' : ''}${summary.stock_total_return_pct.toFixed(2)}%`}
        tone={stockAlphaPositive ? 'green' : 'red'}
      />
      <Metric
        label="Sharpe (年化)"
        primaryValue={summary.sharpe_ratio.toFixed(2)}
        secondaryValue={
          sharpeGood ? '風險調整後表現好' : summary.sharpe_ratio < 0.5 ? '風險調整後普普' : '風險調整後中等'
        }
        tone={sharpeGood ? 'green' : summary.sharpe_ratio < 0.3 ? 'red' : 'neutral'}
      />
      <Metric
        label="Max Drawdown"
        primaryValue={`${summary.max_drawdown_pct.toFixed(2)}%`}
        secondaryValue={
          drawdownSevere
            ? '需要心臟夠強'
            : summary.max_drawdown_pct <= -15
              ? '可接受區間'
              : '波動溫和'
        }
        tone={drawdownSevere ? 'red' : summary.max_drawdown_pct <= -15 ? 'neutral' : 'green'}
      />
      <Metric
        label="勝率"
        primaryValue={summary.n_trades > 0 ? `${summary.win_rate_pct.toFixed(1)}%` : '—'}
        secondaryValue={
          summary.n_trades > 0
            ? `${summary.n_winners}W / ${summary.n_losers}L · 賺 ${summary.avg_win_pct >= 0 ? '+' : ''}${summary.avg_win_pct.toFixed(1)}% / 賠 ${summary.avg_loss_pct.toFixed(1)}%`
            : '尚無交易'
        }
        tone={summary.win_rate_pct >= 50 ? 'green' : summary.win_rate_pct >= 30 ? 'neutral' : 'red'}
      />
      <Metric
        label="In-Market %"
        primaryValue={`${summary.days_in_market_pct.toFixed(1)}%`}
        secondaryValue={`${summary.n_trades} 筆交易;有持倉的天數比例`}
        tone="neutral"
      />
      <Metric
        label="每筆期望值"
        primaryValue={
          summary.n_trades > 0
            ? `${(summary.win_rate_pct / 100 * summary.avg_win_pct + (1 - summary.win_rate_pct / 100) * summary.avg_loss_pct).toFixed(2)}%`
            : '—'
        }
        secondaryValue="勝率×平均賺 + 敗率×平均賠"
        tone={
          summary.n_trades > 0 &&
          summary.win_rate_pct / 100 * summary.avg_win_pct +
            (1 - summary.win_rate_pct / 100) * summary.avg_loss_pct >
            0
            ? 'green'
            : 'red'
        }
      />
    </div>
  );
}

function Metric({
  label,
  primaryValue,
  secondaryValue,
  tone,
}: {
  label: string;
  primaryValue: string;
  secondaryValue: string;
  tone: 'green' | 'red' | 'neutral';
}): JSX.Element {
  const tonePrimary =
    tone === 'green'
      ? 'text-emerald-700'
      : tone === 'red'
        ? 'text-rose-700'
        : 'text-stone-800';
  return (
    <div className="flex flex-col gap-0.5 rounded-md border border-stone-200 bg-white px-3 py-2">
      <span className="text-[10px] font-medium uppercase tracking-wider text-stone-400">
        {label}
      </span>
      <span className={`font-mono text-xl font-bold tabular-nums ${tonePrimary}`}>
        {primaryValue}
      </span>
      <span className="text-[11px] text-stone-500">{secondaryValue}</span>
    </div>
  );
}

interface EquityCurvePoint {
  date: string;
  strategy_value: number;
  spy_baseline_value: number;
  stock_baseline_value: number;
}

function EquityCurve({ data }: { data: ReadonlyArray<EquityCurvePoint> }): JSX.Element {
  const series = useMemo(
    () =>
      data.map((d) => ({
        date: d.date,
        strategy: d.strategy_value,
        spy: d.spy_baseline_value,
        stock: d.stock_baseline_value,
      })),
    [data],
  );
  return (
    <section
      aria-label="資金曲線"
      className="flex flex-col gap-2 rounded-md border border-stone-200 bg-stone-50 p-3"
    >
      <h4 className="text-xs font-medium text-stone-700">
        資金曲線 — 策略 vs SPY B&H vs 股票 B&H
      </h4>
      <IndicatorMultiLine
        series={series}
        lines={[
          { key: 'strategy', label: '策略', color: '#0284c7', width: 2 },
          {
            key: 'stock',
            label: '股票 B&H',
            color: '#16a34a',
            width: 1,
            style: 'dashed',
          },
          {
            key: 'spy',
            label: 'SPY B&H',
            color: '#9ca3af',
            width: 1,
            style: 'dashed',
          },
        ]}
        ariaLabel="策略資金曲線 vs SPY 與股票 buy-and-hold"
      />
    </section>
  );
}

function TradesSection({
  trades,
  isOpen,
  onToggle,
}: {
  trades: ReadonlyArray<PnlTrade>;
  isOpen: boolean;
  onToggle: () => void;
}): JSX.Element {
  if (trades.length === 0) {
    return (
      <p className="text-xs text-stone-500">
        沒有觸發任何交易(可能因為訊號全在 hold/watch 範圍)。
      </p>
    );
  }
  return (
    <div className="flex flex-col gap-2">
      <button
        type="button"
        onClick={onToggle}
        className="flex items-center justify-between rounded-md border border-stone-200 bg-white px-3 py-2 text-sm hover:bg-stone-50"
      >
        <span className="font-medium text-stone-700">
          交易紀錄 ({trades.length} 筆)
        </span>
        <span className="text-xs text-stone-400">{isOpen ? '收合 ▲' : '展開 ▼'}</span>
      </button>
      {isOpen && (
        <div className="overflow-x-auto rounded-md border border-stone-200">
          <table className="w-full text-xs">
            <thead className="bg-stone-100 text-[10px] uppercase tracking-wider text-stone-500">
              <tr>
                <th className="px-2 py-1.5 text-left">進場日</th>
                <th className="px-2 py-1.5 text-left">訊號</th>
                <th className="px-2 py-1.5 text-right">進場價</th>
                <th className="px-2 py-1.5 text-left">出場日</th>
                <th className="px-2 py-1.5 text-right">出場價</th>
                <th className="px-2 py-1.5 text-left">出場原因</th>
                <th className="px-2 py-1.5 text-right">持倉天數</th>
                <th className="px-2 py-1.5 text-right">PnL%</th>
                <th className="px-2 py-1.5 text-right">PnL $</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-stone-200">
              {trades.map((t, i) => {
                const winner = t.pnl_pct > 0;
                return (
                  <tr
                    key={`${t.entry_date}-${i}`}
                    className={winner ? 'bg-emerald-50/30' : 'bg-rose-50/30'}
                  >
                    <td className="px-2 py-1.5 font-mono text-stone-700">{t.entry_date}</td>
                    <td className="px-2 py-1.5 text-stone-700">
                      {ACTION_LABEL[t.entry_action] ?? t.entry_action}
                    </td>
                    <td className="px-2 py-1.5 text-right font-mono text-stone-700">
                      ${t.entry_price.toFixed(2)}
                    </td>
                    <td className="px-2 py-1.5 font-mono text-stone-700">{t.exit_date}</td>
                    <td className="px-2 py-1.5 text-right font-mono text-stone-700">
                      ${t.exit_price.toFixed(2)}
                    </td>
                    <td className="px-2 py-1.5 text-stone-600">
                      {EXIT_REASON_LABEL[t.exit_reason] ?? t.exit_reason}
                    </td>
                    <td className="px-2 py-1.5 text-right font-mono text-stone-500">
                      {t.holding_days}d
                    </td>
                    <td
                      className={`px-2 py-1.5 text-right font-mono font-semibold ${
                        winner ? 'text-emerald-700' : 'text-rose-700'
                      }`}
                    >
                      {t.pnl_pct >= 0 ? '+' : ''}
                      {t.pnl_pct.toFixed(2)}%
                    </td>
                    <td
                      className={`px-2 py-1.5 text-right font-mono ${
                        winner ? 'text-emerald-700' : 'text-rose-700'
                      }`}
                    >
                      {t.pnl_abs >= 0 ? '+' : ''}${t.pnl_abs.toFixed(0)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
