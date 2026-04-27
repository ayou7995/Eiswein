import { z } from 'zod';
import { Explainable, RuleTable } from './Explainable';
import { PositionGauge } from './PositionGauge';
import { TrendPill, type TrendDirection } from './TrendPill';

// VIX detail fields.
//
// The threshold fields and `percentile_1y` were added in INDICATOR_VERSION
// 1.2.0; older rows may not have them. We default thresholds to the current
// industry-convention values (12 / 20 / 30) and treat percentile as
// optional so the prototype renders against pre-1.2.0 snapshots.
const trendDirectionSchema = z.enum(['rising', 'falling', 'flat']);

const vixDetailSchema = z.object({
  level: z.number(),
  ten_day_change: z.number().nullable().optional(),
  trend: trendDirectionSchema.optional().default('flat'),
  percentile_1y: z.number().nullable().optional(),
  threshold_low: z.number().optional().default(12),
  threshold_normal_high: z.number().optional().default(20),
  threshold_elevated_high: z.number().optional().default(30),
});

type VixDetail = z.infer<typeof vixDetailSchema>;
type VixZone = 'low' | 'normal' | 'elevated' | 'panic';

function classifyZone(d: VixDetail): VixZone {
  if (d.level < d.threshold_low) return 'low';
  if (d.level <= d.threshold_normal_high) return 'normal';
  if (d.level <= d.threshold_elevated_high) return 'elevated';
  return 'panic';
}

const ZONE_LABEL: Record<VixZone, string> = {
  low: '🟡 自滿',
  normal: '🟢 正常',
  elevated: '🟡 警戒',
  panic: '🔴 恐慌',
};

interface ZoneVerdict {
  signalLabel: string;
  axisLabel: string;
}

const ZONE_VERDICT: Record<VixZone, ZoneVerdict> = {
  low: { signalLabel: '🟡 自滿', axisLabel: '自滿' },
  normal: { signalLabel: '🟢 正常', axisLabel: '正常' },
  elevated: { signalLabel: '🟡 警戒', axisLabel: '警戒' },
  panic: { signalLabel: '🔴 恐慌', axisLabel: '恐慌' },
};

const TREND_INTERPRETATIONS: Record<TrendDirection, string> = {
  rising: '恐慌升溫，對股市偏弱',
  falling: '恐慌降溫，對股市友善',
  flat: '情緒未變，續觀察',
  unknown: '資料不足以計算',
};

// Range cap for the position gauge — VIX practically lives in 0-50 even in
// crashes (rare touches of 80 in 2020/COVID), so 50 keeps the marker visible
// without distorting day-to-day position.
const VIX_GAUGE_MIN = 0;
const VIX_GAUGE_MAX = 50;

export interface VixHeadlineLabels {
  ruleTitle: string;
  ruleNote: string;
}

export function VixHeadlineExplainable({
  shortLabel,
  detail,
  labels,
}: {
  shortLabel: string;
  detail: Record<string, unknown>;
  labels: VixHeadlineLabels;
}): JSX.Element {
  const parsed = vixDetailSchema.safeParse(detail);
  if (!parsed.success) return <span>{shortLabel}</span>;
  const d = parsed.data;
  const zone = classifyZone(d);
  return (
    <Explainable
      title={labels.ruleTitle}
      explanation={
        <RuleTable
          preface="VIX 衡量 SPX 30 天隱含波動率；通常與股市反向。"
          rows={[
            {
              condition: `level < ${d.threshold_low}`,
              result: '🟡 自滿（過度樂觀，反向訊號）',
              current: zone === 'low',
            },
            {
              condition: `${d.threshold_low} ≤ level ≤ ${d.threshold_normal_high}`,
              result: '🟢 正常',
              current: zone === 'normal',
            },
            {
              condition: `${d.threshold_normal_high} < level ≤ ${d.threshold_elevated_high}`,
              result: '🟡 警戒（壓力升高）',
              current: zone === 'elevated',
            },
            {
              condition: `level > ${d.threshold_elevated_high}`,
              result: '🔴 恐慌（賣壓主導）',
              current: zone === 'panic',
            },
          ]}
          currentValueText={`你目前: VIX = ${d.level.toFixed(2)} → ${ZONE_LABEL[zone]}`}
          note={labels.ruleNote}
        />
      }
    >
      {shortLabel}
    </Explainable>
  );
}

export function VixEnhancedDetail({
  detail,
}: {
  detail: Record<string, unknown>;
}): JSX.Element | null {
  const parsed = vixDetailSchema.safeParse(detail);
  if (!parsed.success) return null;
  const d = parsed.data;
  const zone = classifyZone(d);
  const verdict = ZONE_VERDICT[zone];

  const zones = [
    {
      upTo: d.threshold_low,
      label: '自滿',
      bg: 'bg-amber-400/30',
      text: 'text-amber-400',
    },
    {
      upTo: d.threshold_normal_high,
      label: '正常',
      bg: 'bg-signal-green/30',
      text: 'text-signal-green',
    },
    {
      upTo: d.threshold_elevated_high,
      label: '警戒',
      bg: 'bg-amber-400/30',
      text: 'text-amber-400',
    },
    {
      upTo: VIX_GAUGE_MAX,
      label: '恐慌',
      bg: 'bg-signal-red/30',
      text: 'text-signal-red',
    },
  ];

  const trendDirection: TrendDirection = d.trend ?? 'flat';
  const tenDayChange = d.ten_day_change ?? null;

  return (
    <div className="flex flex-col gap-4 px-3 py-3 text-sm">
      <PositionSection
        d={d}
        zones={zones}
        zoneAxisLabel={verdict.axisLabel}
      />
      <TrendPill
        direction={trendDirection}
        magnitude={tenDayChange}
        windowLabel="10 日變化"
        interpretations={TREND_INTERPRETATIONS}
      />
      <Watchpoints zone={zone} detail={d} />
    </div>
  );
}

function PositionSection({
  d,
  zones,
  zoneAxisLabel,
}: {
  d: VixDetail;
  zones: ReadonlyArray<{
    upTo: number;
    label: string;
    bg: string;
    text: string;
  }>;
  zoneAxisLabel: string;
}): JSX.Element {
  const percentile = d.percentile_1y ?? null;
  return (
    <section aria-label="VIX 位置條" className="flex flex-col gap-2 text-xs">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-slate-400">位置（0–{VIX_GAUGE_MAX} 區間）</h3>
        <span className="text-slate-400">
          <span className="font-mono tabular-nums text-slate-100">
            {d.level.toFixed(2)}
          </span>
          {percentile !== null && (
            <>
              <span className="mx-1 text-slate-600">·</span>
              <span>
                過去 1 年{' '}
                <span className="font-mono tabular-nums text-slate-200">
                  {Math.round(percentile * 100)}%
                </span>
                <span className="ml-1 text-slate-500">
                  ({describePercentile(percentile)})
                </span>
              </span>
            </>
          )}
        </span>
      </div>
      <PositionGauge
        value={d.level}
        min={VIX_GAUGE_MIN}
        max={VIX_GAUGE_MAX}
        zones={zones}
        ariaLabel={`VIX 位置 ${d.level.toFixed(2)}，落在 ${zoneAxisLabel} 區`}
        highlightCurrentZone
      />
    </section>
  );
}

function describePercentile(p: number): string {
  if (p >= 0.9) return '近 1 年最高側';
  if (p >= 0.7) return '偏高側';
  if (p >= 0.3) return '中段';
  if (p >= 0.1) return '偏低側';
  return '近 1 年最低側';
}

interface WatchpointEntry {
  direction: 'up' | 'down';
  threshold: number;
  nextZone: VixZone;
}

function buildWatchpoints(zone: VixZone, d: VixDetail): WatchpointEntry[] {
  if (zone === 'low') {
    return [
      { direction: 'up', threshold: d.threshold_low, nextZone: 'normal' },
    ];
  }
  if (zone === 'normal') {
    return [
      { direction: 'down', threshold: d.threshold_low, nextZone: 'low' },
      { direction: 'up', threshold: d.threshold_normal_high, nextZone: 'elevated' },
    ];
  }
  if (zone === 'elevated') {
    return [
      { direction: 'down', threshold: d.threshold_normal_high, nextZone: 'normal' },
      { direction: 'up', threshold: d.threshold_elevated_high, nextZone: 'panic' },
    ];
  }
  return [
    { direction: 'down', threshold: d.threshold_elevated_high, nextZone: 'elevated' },
    { direction: 'down', threshold: d.threshold_normal_high, nextZone: 'normal' },
  ];
}

function Watchpoints({
  zone,
  detail,
}: {
  zone: VixZone;
  detail: VixDetail;
}): JSX.Element {
  const points = buildWatchpoints(zone, detail);
  return (
    <section aria-label="VIX 看點" className="flex flex-col gap-2 text-xs">
      <h3 className="text-slate-400">
        <Explainable
          title="看點生成規則"
          explanation={
            <RuleTable
              preface="依目前所在區塊決定要顯示哪些閾值轉換："
              rows={[
                {
                  condition: '🟡 自滿 (<12)',
                  result: '只看「站上 12 → 正常」',
                  current: zone === 'low',
                },
                {
                  condition: '🟢 正常 (12-20)',
                  result: '雙向（破 12 → 自滿 / 破 20 → 警戒）',
                  current: zone === 'normal',
                },
                {
                  condition: '🟡 警戒 (20-30)',
                  result: '雙向（破 20 → 正常 / 破 30 → 恐慌）',
                  current: zone === 'elevated',
                },
                {
                  condition: '🔴 恐慌 (>30)',
                  result: '兩條皆為「恢復條件」',
                  current: zone === 'panic',
                },
              ]}
              note="閾值 12 / 20 / 30 是業界常見分區（CBOE / O'Neil 系統）。"
            />
          }
        >
          看點
        </Explainable>
        （觸發轉態勢的關鍵 VIX 值）
      </h3>
      <ul className="flex flex-col gap-1.5">
        {points.map((p) => (
          <li
            key={`${p.direction}-${p.threshold}`}
            className="flex flex-wrap items-center gap-2 rounded-md border border-slate-800 bg-slate-950/40 px-2 py-1.5"
          >
            <span className="text-slate-300">
              {p.direction === 'up' ? '突破' : '跌破'} {p.threshold}
            </span>
            <span className="text-slate-500">→</span>
            <span className="text-slate-300">{ZONE_LABEL[p.nextZone]}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
