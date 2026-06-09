import { z } from 'zod';
import { Explainable, RuleTable } from './Explainable';
import { PositionGauge, type PositionGaugeZone } from './PositionGauge';

interface SkewWatchpoint {
  direction: 'up' | 'down';
  threshold: number;
  nextLabel: string;
}

// CBOE Skew Index detail fields. Mirrors the indicator output in
// ``backend/app/indicators/market_regime/skew.py`` — three-zone
// system (normal / elevated / high) keyed off the level.
const skewDetailSchema = z.object({
  level: z.number(),
  ten_day_change: z.number().nullable().optional(),
  trend: z.enum(['rising', 'falling', 'flat']).optional().default('flat'),
  percentile_1y: z.number().nullable().optional(),
  threshold_normal_high: z.number().optional().default(130),
  threshold_elevated_high: z.number().optional().default(145),
});

type SkewDetail = z.infer<typeof skewDetailSchema>;
type SkewZone = 'normal' | 'elevated' | 'high';

function classifyZone(d: SkewDetail): SkewZone {
  if (d.level <= d.threshold_normal_high) return 'normal';
  if (d.level < d.threshold_elevated_high) return 'elevated';
  return 'high';
}

const ZONE_LABEL: Record<SkewZone, string> = {
  normal: '🟢 尾部風險低',
  elevated: '🟡 尾部風險上升',
  high: '🔴 機構避險',
};

// SKEW historically lives in ~110-160 — gauge widened slightly to keep
// the marker comfortably inside the bounds at extremes.
const SKEW_GAUGE_MIN = 100;
const SKEW_GAUGE_MAX = 170;

export interface SkewHeadlineLabels {
  ruleTitle: string;
  ruleNote: string;
}

export function SkewHeadlineExplainable({
  shortLabel,
  detail,
  labels,
}: {
  shortLabel: string;
  detail: Record<string, unknown>;
  labels: SkewHeadlineLabels;
}): JSX.Element {
  const parsed = skewDetailSchema.safeParse(detail);
  if (!parsed.success) return <span>{shortLabel}</span>;
  const d = parsed.data;
  const zone = classifyZone(d);
  return (
    <Explainable
      title={labels.ruleTitle}
      explanation={
        <RuleTable
          preface="SKEW 衡量 SPX OTM put 的相對溢價 — 機構買保險越積極,SKEW 越高。100 = 對數常態分布;越高 = 尾部分布越胖。"
          rows={[
            {
              condition: `level ≤ ${d.threshold_normal_high}`,
              result: '🟢 尾部風險低',
              current: zone === 'normal',
            },
            {
              condition: `${d.threshold_normal_high} < level < ${d.threshold_elevated_high}`,
              result: '🟡 尾部風險上升',
              current: zone === 'elevated',
            },
            {
              condition: `level ≥ ${d.threshold_elevated_high}`,
              result: '🔴 機構避險（OTM put 顯著走貴）',
              current: zone === 'high',
            },
          ]}
          currentValueText={`你目前: SKEW = ${d.level.toFixed(0)} → ${ZONE_LABEL[zone]}`}
          note={labels.ruleNote}
        />
      }
    >
      {shortLabel}
    </Explainable>
  );
}

export function SkewEnhancedDetail({
  detail,
}: {
  detail: Record<string, unknown>;
}): JSX.Element | null {
  const parsed = skewDetailSchema.safeParse(detail);
  if (!parsed.success) return null;
  const d = parsed.data;
  const zone = classifyZone(d);
  const percentile = d.percentile_1y ?? null;
  const tenDayChange = d.ten_day_change ?? null;

  const zones: ReadonlyArray<PositionGaugeZone> = [
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
      text: 'text-amber-700',
    },
    {
      upTo: SKEW_GAUGE_MAX,
      label: '高風險',
      bg: 'bg-signal-red/30',
      text: 'text-signal-red',
    },
  ];

  return (
    <div className="flex flex-col gap-3 px-3 py-3 text-sm">
      <section
        aria-label="SKEW 位置條"
        className="flex flex-col gap-2 text-xs"
      >
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h3 className="text-stone-500">
            位置（{SKEW_GAUGE_MIN}-{SKEW_GAUGE_MAX} 區間）
          </h3>
          <span className="text-stone-500">
            <span className="font-mono tabular-nums text-stone-900">
              {d.level.toFixed(0)}
            </span>
            {percentile !== null && (
              <>
                <span className="mx-1 text-stone-400">·</span>
                <span>
                  過去 1 年{' '}
                  <span className="font-mono tabular-nums text-stone-800">
                    {Math.round(percentile * 100)}%
                  </span>
                </span>
              </>
            )}
            {tenDayChange !== null && (
              <>
                <span className="mx-1 text-stone-400">·</span>
                <span>
                  10 日{' '}
                  <span className="font-mono tabular-nums text-stone-700">
                    {tenDayChange >= 0 ? '+' : ''}
                    {tenDayChange.toFixed(1)}
                  </span>
                </span>
              </>
            )}
          </span>
        </div>
        <PositionGauge
          value={Math.max(SKEW_GAUGE_MIN, Math.min(SKEW_GAUGE_MAX, d.level))}
          min={SKEW_GAUGE_MIN}
          max={SKEW_GAUGE_MAX}
          zones={zones}
          ariaLabel={`SKEW ${d.level.toFixed(0)},${ZONE_LABEL[zone]}`}
          highlightCurrentZone
        />
      </section>
      <TonePill zone={zone} level={d.level} />
      <Watchpoints zone={zone} detail={d} />
    </div>
  );
}

function TonePill({
  zone,
  level,
}: {
  zone: SkewZone;
  level: number;
}): JSX.Element {
  const tone =
    zone === 'high'
      ? 'border-signal-red/40 bg-signal-red/10 text-signal-red'
      : zone === 'elevated'
        ? 'border-amber-400/40 bg-amber-50 text-amber-700'
        : 'border-signal-green/40 bg-signal-green/10 text-signal-green';
  const summary =
    zone === 'high'
      ? `🔴 機構避險 — OTM put 顯著走貴 (level ${level.toFixed(0)})`
      : zone === 'elevated'
        ? `🟡 尾部風險上升 — 機構開始買保險 (level ${level.toFixed(0)})`
        : `🟢 尾部風險低 — 無顯著機構避險訊號 (level ${level.toFixed(0)})`;
  return (
    <section
      aria-label="SKEW 判讀"
      className={`flex items-center gap-2 rounded-md border px-3 py-2 text-xs ${tone}`}
    >
      <span className="font-medium">{summary}</span>
    </section>
  );
}

function buildWatchpoints(zone: SkewZone, d: SkewDetail): SkewWatchpoint[] {
  if (zone === 'normal') {
    return [
      { direction: 'up', threshold: d.threshold_normal_high, nextLabel: ZONE_LABEL.elevated },
    ];
  }
  if (zone === 'elevated') {
    return [
      { direction: 'down', threshold: d.threshold_normal_high, nextLabel: ZONE_LABEL.normal },
      { direction: 'up', threshold: d.threshold_elevated_high, nextLabel: ZONE_LABEL.high },
    ];
  }
  return [
    { direction: 'down', threshold: d.threshold_elevated_high, nextLabel: ZONE_LABEL.elevated },
    { direction: 'down', threshold: d.threshold_normal_high, nextLabel: ZONE_LABEL.normal },
  ];
}

function Watchpoints({
  zone,
  detail,
}: {
  zone: SkewZone;
  detail: SkewDetail;
}): JSX.Element {
  const points = buildWatchpoints(zone, detail);
  return (
    <section aria-label="SKEW 看點" className="flex flex-col gap-2 text-xs">
      <h3 className="text-stone-500">
        <Explainable
          title="看點生成規則"
          explanation={
            <RuleTable
              preface="依目前所在區塊決定要顯示哪些閾值轉換："
              rows={[
                {
                  condition: '🟢 正常 (≤130)',
                  result: '只看「站上 130 → 警戒」',
                  current: zone === 'normal',
                },
                {
                  condition: '🟡 警戒 (130-145)',
                  result: '雙向(破 130 → 正常 / 破 145 → 機構避險)',
                  current: zone === 'elevated',
                },
                {
                  condition: '🔴 機構避險 (≥145)',
                  result: '兩條皆為「恢復條件」',
                  current: zone === 'high',
                },
              ]}
              note="閾值 130 / 145 是業界 SKEW tail-risk 分區。"
            />
          }
        >
          看點
        </Explainable>
        <span className="ml-1 text-stone-400">（觸發轉態勢的關鍵 SKEW 值）</span>
      </h3>
      <ul className="flex flex-col gap-1">
        {points.map((p) => (
          <li
            key={`${p.direction}-${p.threshold}`}
            className="flex flex-wrap items-center gap-2 rounded-md border border-stone-200 bg-stone-50 px-2 py-1"
          >
            <span className="text-stone-700">
              {p.direction === 'up' ? '突破' : '跌破'} {p.threshold.toFixed(0)}
            </span>
            <span className="text-stone-400">→</span>
            <span className="text-stone-700">{p.nextLabel}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
