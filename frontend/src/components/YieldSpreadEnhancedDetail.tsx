import { useMemo } from 'react';
import { z } from 'zod';
import { Explainable, RuleTable } from './Explainable';
import { PositionGauge, type PositionGaugeZone } from './PositionGauge';
import { useMarketIndicatorSeries } from '../hooks/useMarketIndicatorSeries';

// Detail emitted by `app/indicators/market_regime/yield_spread.py`. Shape
// stable since v1.0.0; no schema relaxation needed beyond the standard
// missing-field tolerance the indicator already provides.
const yieldSpreadDetailSchema = z.object({
  spread: z.number(),
  ten_year: z.number(),
  two_year: z.number(),
  recent_inversion_transition: z
    .enum(['became_inverted', 'became_normal', 'none'])
    .optional()
    .default('none'),
});

type YieldSpreadDetail = z.infer<typeof yieldSpreadDetailSchema>;
type YieldSpreadSignal = 'healthy' | 'flattening' | 'inverted';

const HEALTHY_THRESHOLD = 0.2;

function classifySignal(d: YieldSpreadDetail): YieldSpreadSignal {
  if (d.spread > HEALTHY_THRESHOLD) return 'healthy';
  if (d.spread > 0) return 'flattening';
  return 'inverted';
}

const SIGNAL_LABEL: Record<YieldSpreadSignal, string> = {
  healthy: '🟢 健康',
  flattening: '🟡 趨平',
  inverted: '🔴 倒掛',
};

const GAUGE_MIN = -1;
const GAUGE_MAX = 2;

const ZONES: ReadonlyArray<PositionGaugeZone> = [
  { upTo: 0, label: '倒掛', bg: 'bg-signal-red/30', text: 'text-signal-red' },
  { upTo: HEALTHY_THRESHOLD, label: '趨平', bg: 'bg-amber-400/30', text: 'text-amber-400' },
  { upTo: GAUGE_MAX, label: '健康', bg: 'bg-signal-green/30', text: 'text-signal-green' },
];

export interface YieldSpreadHeadlineLabels {
  ruleTitle: string;
  ruleNote: string;
}

export function YieldSpreadHeadlineExplainable({
  shortLabel,
  detail,
  labels,
}: {
  shortLabel: string;
  detail: Record<string, unknown>;
  labels: YieldSpreadHeadlineLabels;
}): JSX.Element {
  const parsed = yieldSpreadDetailSchema.safeParse(detail);
  if (!parsed.success) return <span>{shortLabel}</span>;
  const d = parsed.data;
  const signal = classifySignal(d);
  return (
    <Explainable
      title={labels.ruleTitle}
      explanation={
        <RuleTable
          preface="10 年期減 2 年期公債殖利率差。倒掛 (spread<0) 是衰退領先指標 (avg lead 12-18 個月)。"
          rows={[
            {
              condition: 'spread > +0.2',
              result: '🟢 健康（正常陡峭曲線）',
              current: signal === 'healthy',
            },
            {
              condition: '0 < spread ≤ +0.2',
              result: '🟡 趨平（接近倒掛警戒）',
              current: signal === 'flattening',
            },
            {
              condition: 'spread ≤ 0',
              result: '🔴 倒掛（衰退訊號）',
              current: signal === 'inverted',
            },
          ]}
          currentValueText={`你目前: 10Y=${d.ten_year.toFixed(2)}%, 2Y=${d.two_year.toFixed(2)}% → spread=${formatSpread(d.spread)} → ${SIGNAL_LABEL[signal]}`}
          note={labels.ruleNote}
        />
      }
    >
      {shortLabel}
    </Explainable>
  );
}

export function YieldSpreadEnhancedDetail({
  detail,
}: {
  detail: Record<string, unknown>;
}): JSX.Element | null {
  const parsed = yieldSpreadDetailSchema.safeParse(detail);
  if (!parsed.success) return null;
  const d = parsed.data;
  const signal = classifySignal(d);

  return (
    <div className="flex flex-col gap-3 px-3 py-3 text-sm">
      <PositionSection spread={d.spread} tenYear={d.ten_year} twoYear={d.two_year} />
      <InversionStatusSection />
      <Watchpoints signal={signal} />
    </div>
  );
}

function PositionSection({
  spread,
  tenYear,
  twoYear,
}: {
  spread: number;
  tenYear: number;
  twoYear: number;
}): JSX.Element {
  return (
    <section aria-label="利差位置條" className="flex flex-col gap-2 text-xs">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-slate-400">利差位置（-1 ~ +2）</h3>
        <span className="text-slate-400">
          <span className="text-sky-400">10Y {tenYear.toFixed(2)}%</span>
          <span className="mx-1 text-slate-600">·</span>
          <span className="text-amber-400">2Y {twoYear.toFixed(2)}%</span>
          <span className="mx-1 text-slate-600">·</span>
          <span className="font-mono tabular-nums text-slate-100">{formatSpread(spread)}</span>
          <span className="ml-1 text-[10px] text-slate-500">利差</span>
        </span>
      </div>
      <PositionGauge
        value={spread}
        min={GAUGE_MIN}
        max={GAUGE_MAX}
        zones={ZONES}
        ariaLabel={`10Y-2Y 利差 ${formatSpread(spread)}`}
        highlightCurrentZone
      />
    </section>
  );
}

// Inversion timing — leading indicator angle that's unique to yield_spread.
// We pull `days_since_inversion` and `last_inversion_end` off the chart
// series response (already cached by React Query for the chart above), so
// no extra fetch and no backend changes.
function InversionStatusSection(): JSX.Element | null {
  const series = useMarketIndicatorSeries('yield_spread');
  const status = useMemo(() => {
    if (series.data === undefined || series.data.indicator !== 'yield_spread') {
      return null;
    }
    return series.data.current;
  }, [series.data]);

  if (status === null) return null;
  return <InversionBadge status={status} />;
}

interface InversionStatus {
  spread: number;
  days_since_inversion: number | null;
  last_inversion_end: string | null;
}

function InversionBadge({ status }: { status: InversionStatus }): JSX.Element {
  const display = describeInversion(status);
  return (
    <section
      aria-label="倒掛狀態"
      className={`flex items-center gap-2 rounded-md border px-3 py-2 text-xs ${display.tone}`}
    >
      <span aria-hidden="true">{display.emoji}</span>
      <Explainable
        title="倒掛狀態解讀"
        explanation={
          <RuleTable
            preface="倒掛是衰退領先指標 — 平均提早 12-18 個月反映在實際衰退。"
            rows={[
              {
                condition: 'spread < 0（持續中）',
                result: '🔴 目前倒掛 N 天 — 衰退時鐘已啟動',
                current: status.spread < 0,
              },
              {
                condition: '近期倒掛已結束（spread 翻正）',
                result: '🟡 結束後 N 天 — 衰退風險最高的窗口',
                current: status.spread >= 0 && status.days_since_inversion !== null,
              },
              {
                condition: '60 日窗口內無倒掛',
                result: '🟢 過去 60 天無倒掛紀錄',
                current: status.spread >= 0 && status.days_since_inversion === null,
              },
            ]}
            note="倒掛結束後而非開始時是「最危險窗口」— 美國過去 5 次衰退都是在倒掛結束後 6-18 個月才實際發生。"
          />
        }
      >
        <span>{display.label}</span>
      </Explainable>
    </section>
  );
}

function describeInversion(status: InversionStatus): {
  emoji: string;
  label: string;
  tone: string;
} {
  if (status.spread < 0) {
    return {
      emoji: '🔴',
      label: '目前處於倒掛中（衰退時鐘啟動）',
      tone: 'border-signal-red/40 bg-signal-red/10 text-signal-red',
    };
  }
  if (status.days_since_inversion !== null) {
    const since = status.last_inversion_end ?? '未知日期';
    const days = status.days_since_inversion;
    return {
      emoji: '🟡',
      label: `倒掛結束後 ${days} 天（最近一次：${since}）— 衰退風險窗口`,
      tone: 'border-amber-400/40 bg-amber-400/10 text-amber-400',
    };
  }
  return {
    emoji: '🟢',
    label: '過去 60 天無倒掛紀錄',
    tone: 'border-signal-green/40 bg-signal-green/10 text-signal-green',
  };
}

interface Watchpoint {
  direction: 'up' | 'down';
  threshold: number;
  nextSignal: YieldSpreadSignal;
}

function buildWatchpoints(signal: YieldSpreadSignal): Watchpoint[] {
  if (signal === 'healthy') {
    return [
      { direction: 'down', threshold: HEALTHY_THRESHOLD, nextSignal: 'flattening' },
      { direction: 'down', threshold: 0, nextSignal: 'inverted' },
    ];
  }
  if (signal === 'flattening') {
    return [
      { direction: 'up', threshold: HEALTHY_THRESHOLD, nextSignal: 'healthy' },
      { direction: 'down', threshold: 0, nextSignal: 'inverted' },
    ];
  }
  return [
    { direction: 'up', threshold: 0, nextSignal: 'flattening' },
    { direction: 'up', threshold: HEALTHY_THRESHOLD, nextSignal: 'healthy' },
  ];
}

function Watchpoints({ signal }: { signal: YieldSpreadSignal }): JSX.Element {
  const points = buildWatchpoints(signal);
  return (
    <section aria-label="利差看點" className="flex flex-col gap-1.5 text-xs">
      <h3 className="text-slate-400">
        <Explainable
          title="看點生成規則"
          explanation={
            <RuleTable
              preface="依目前利差區段決定要顯示哪些閾值轉換："
              rows={[
                {
                  condition: '🟢 健康 (>+0.2)',
                  result: '兩條皆為下方威脅（趨平 / 倒掛）',
                  current: signal === 'healthy',
                },
                {
                  condition: '🟡 趨平 (0 ~ +0.2)',
                  result: '雙向（站回 +0.2 / 跌破 0）',
                  current: signal === 'flattening',
                },
                {
                  condition: '🔴 倒掛 (≤0)',
                  result: '兩條皆為恢復條件（站回 0 / 站回 +0.2）',
                  current: signal === 'inverted',
                },
              ]}
              note="閾值 0 是衰退領先訊號；+0.2 是業界常用的「健康陡峭」門檻。"
            />
          }
        >
          看點
        </Explainable>
        <span className="ml-1 text-slate-500">（觸發轉態勢的關鍵利差）</span>
      </h3>
      <ul className="flex flex-col gap-1">
        {points.map((p) => (
          <li
            key={`${p.direction}-${p.threshold}`}
            className="flex flex-wrap items-center gap-2 rounded-md border border-slate-800 bg-slate-950/40 px-2 py-1"
          >
            <span className="text-slate-300">
              {p.direction === 'up' ? '站上' : '跌破'} {formatSpread(p.threshold)}
            </span>
            <span className="text-slate-500">→</span>
            <span className="text-slate-300">{SIGNAL_LABEL[p.nextSignal]}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function formatSpread(n: number): string {
  return n >= 0 ? `+${n.toFixed(2)}` : n.toFixed(2);
}
