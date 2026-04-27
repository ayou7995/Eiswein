import { useMemo } from 'react';
import { z } from 'zod';
import { Explainable, RuleTable } from './Explainable';
import { TrendPill, type TrendDirection } from './TrendPill';
import { useMarketIndicatorSeries } from '../hooks/useMarketIndicatorSeries';

// Fed Funds Rate detail emitted by `app/indicators/macro/fed_rate.py`.
// The regime is delta-driven (30-day change), not level-driven. The
// chart-series response carries richer context (last FOMC change date /
// direction) which we surface as a separate badge.
const fedDetailSchema = z.object({
  current: z.number(),
  prior_30d: z.number(),
  delta_30d: z.number(),
});

type FedDetail = z.infer<typeof fedDetailSchema>;
type FedSignal = 'cutting' | 'holding' | 'hiking';

const HIKE_THRESHOLD = 0.25;

function classifySignal(d: FedDetail): FedSignal {
  if (d.delta_30d < -HIKE_THRESHOLD) return 'cutting';
  if (d.delta_30d > HIKE_THRESHOLD) return 'hiking';
  return 'holding';
}

const SIGNAL_LABEL: Record<FedSignal, string> = {
  cutting: '🟢 降息中（對股市友善）',
  holding: '🟡 持平',
  hiking: '🔴 升息中（對股市偏弱）',
};

const TREND_INTERPRETATIONS: Record<TrendDirection, string> = {
  rising: 'Fed 升息中，股市偏弱',
  falling: 'Fed 降息中，股市友善',
  flat: 'Fed 持平，無方向',
  unknown: '資料不足',
};

function trendDirection(d: FedDetail): TrendDirection {
  if (d.delta_30d > HIKE_THRESHOLD) return 'rising';
  if (d.delta_30d < -HIKE_THRESHOLD) return 'falling';
  return 'flat';
}

export interface FedRateHeadlineLabels {
  ruleTitle: string;
  ruleNote: string;
}

export function FedRateHeadlineExplainable({
  shortLabel,
  detail,
  labels,
}: {
  shortLabel: string;
  detail: Record<string, unknown>;
  labels: FedRateHeadlineLabels;
}): JSX.Element {
  const parsed = fedDetailSchema.safeParse(detail);
  if (!parsed.success) return <span>{shortLabel}</span>;
  const d = parsed.data;
  const signal = classifySignal(d);
  return (
    <Explainable
      title={labels.ruleTitle}
      explanation={
        <RuleTable
          preface="Fed Funds Rate 30 日變化決定升/降息週期方向："
          rows={[
            {
              condition: 'Δ < -0.25',
              result: '🟢 降息中（對股市友善）',
              current: signal === 'cutting',
            },
            {
              condition: '|Δ| ≤ 0.25',
              result: '🟡 持平',
              current: signal === 'holding',
            },
            {
              condition: 'Δ > +0.25',
              result: '🔴 升息中（對股市偏弱）',
              current: signal === 'hiking',
            },
          ]}
          currentValueText={`你目前: 利率 ${d.current.toFixed(2)}%，30 日前 ${d.prior_30d.toFixed(2)}% → Δ ${formatDelta(d.delta_30d)} → ${SIGNAL_LABEL[signal]}`}
          note={labels.ruleNote}
        />
      }
    >
      {shortLabel}
    </Explainable>
  );
}

export function FedRateEnhancedDetail({
  detail,
}: {
  detail: Record<string, unknown>;
}): JSX.Element | null {
  const parsed = fedDetailSchema.safeParse(detail);
  if (!parsed.success) return null;
  const d = parsed.data;
  return (
    <div className="flex flex-col gap-3 px-3 py-3 text-sm">
      <TrendPill
        direction={trendDirection(d)}
        magnitude={d.delta_30d}
        windowLabel="30 日變化"
        interpretations={TREND_INTERPRETATIONS}
      />
      <LastFedActionSection currentRate={d.current} />
    </div>
  );
}

// Last FOMC change context — pulls from the chart-series response (cached
// by React Query) so we get `last_change_date` / `last_change_direction`
// without an extra fetch when the chart is also rendered.
function LastFedActionSection({
  currentRate,
}: {
  currentRate: number;
}): JSX.Element | null {
  const series = useMarketIndicatorSeries('fed_rate');
  const action = useMemo(() => {
    if (series.data === undefined || series.data.indicator !== 'fed_rate') return null;
    return series.data.current;
  }, [series.data]);
  if (action === null) return null;
  return <LastFedActionBadge action={action} currentRate={currentRate} />;
}

interface FedActionData {
  current_rate: number;
  prior_30d_rate: number;
  delta_30d: number;
  days_since_last_change: number | null;
  last_change_date: string | null;
  last_change_direction: 'hike' | 'cut' | null;
}

function LastFedActionBadge({
  action,
  currentRate,
}: {
  action: FedActionData;
  currentRate: number;
}): JSX.Element {
  const display = describeLastAction(action);
  return (
    <section
      aria-label="Fed 最近一次動作"
      className={`flex items-center gap-2 rounded-md border px-3 py-2 text-xs ${display.tone}`}
    >
      <span aria-hidden="true">{display.emoji}</span>
      <Explainable
        title="最近 FOMC 動作解讀"
        explanation={
          <RuleTable
            preface="顯示 365 日窗口內最近一次利率變動（hike/cut）的時點與方向。"
            rows={[
              {
                condition: '近期 cut + 距今 < 60 天',
                result: '🟢 降息週期啟動初期',
                current:
                  action.last_change_direction === 'cut' &&
                  action.days_since_last_change !== null &&
                  action.days_since_last_change < 60,
              },
              {
                condition: '近期 hike + 距今 < 60 天',
                result: '🔴 升息週期啟動初期',
                current:
                  action.last_change_direction === 'hike' &&
                  action.days_since_last_change !== null &&
                  action.days_since_last_change < 60,
              },
              {
                condition: '距今 ≥ 60 天',
                result: '🟡 暫停期 — Fed 觀望中',
                current:
                  action.days_since_last_change !== null &&
                  action.days_since_last_change >= 60,
              },
              {
                condition: '365 日窗口內無變動',
                result: '⚪ 長期持平',
                current: action.last_change_date === null,
              },
            ]}
            currentValueText={`目前利率 ${currentRate.toFixed(2)}%`}
            note="FOMC 一般每 6-8 週開會一次。「暫停期」並非中性 — 取決於前一次是升或降，可能延續或反轉。"
          />
        }
      >
        <span>{display.label}</span>
      </Explainable>
    </section>
  );
}

function describeLastAction(action: FedActionData): {
  emoji: string;
  label: string;
  tone: string;
} {
  if (action.last_change_date === null || action.days_since_last_change === null) {
    return {
      emoji: '⚪',
      label: '365 日窗口內無利率變動（長期持平）',
      tone: 'border-slate-700 bg-slate-950/40 text-slate-300',
    };
  }
  const days = action.days_since_last_change;
  const isRecent = days < 60;
  const dirLabel = action.last_change_direction === 'cut' ? '降息' : '升息';
  if (action.last_change_direction === 'cut') {
    return {
      emoji: isRecent ? '🟢' : '🟡',
      label: `最近一次 ${dirLabel}：${action.last_change_date}（${days} 天前${isRecent ? '，週期啟動初期' : '，已進入暫停期'}）`,
      tone: isRecent
        ? 'border-signal-green/40 bg-signal-green/10 text-signal-green'
        : 'border-amber-400/40 bg-amber-400/10 text-amber-400',
    };
  }
  return {
    emoji: isRecent ? '🔴' : '🟡',
    label: `最近一次 ${dirLabel}：${action.last_change_date}（${days} 天前${isRecent ? '，週期啟動初期' : '，已進入暫停期'}）`,
    tone: isRecent
      ? 'border-signal-red/40 bg-signal-red/10 text-signal-red'
      : 'border-amber-400/40 bg-amber-400/10 text-amber-400',
  };
}

function formatDelta(n: number): string {
  return `${n >= 0 ? '+' : ''}${n.toFixed(2)}`;
}
