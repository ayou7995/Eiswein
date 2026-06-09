import { z } from 'zod';
import { Explainable, RuleTable } from './Explainable';
import { PositionGauge, type PositionGaugeZone } from './PositionGauge';

interface UnrateWatchpoint {
  direction: 'up' | 'down';
  threshold: number;
  nextLabel: string;
}

// UNRATE + Sahm Rule detail fields. Mirrors the indicator output in
// ``backend/app/indicators/market_regime/unrate.py``. The voting signal
// is keyed on ``sahm_value``; ``current_rate`` / ``twelve_month_low``
// surface as supporting context.
const unrateDetailSchema = z.object({
  current_rate: z.number(),
  prior_month_rate: z.number().optional(),
  three_month_avg: z.number(),
  twelve_month_low: z.number(),
  sahm_value: z.number(),
  sahm_distance_to_trigger: z.number().optional(),
  threshold_warning: z.number().optional().default(0.3),
  threshold_trigger: z.number().optional().default(0.5),
});

type UnrateDetail = z.infer<typeof unrateDetailSchema>;
type UnrateZone = 'healthy' | 'warning' | 'recession';

function classifyZone(d: UnrateDetail): UnrateZone {
  if (d.sahm_value >= d.threshold_trigger) return 'recession';
  if (d.sahm_value >= d.threshold_warning) return 'warning';
  return 'healthy';
}

const ZONE_LABEL: Record<UnrateZone, string> = {
  healthy: '🟢 失業率穩定',
  warning: '🟡 失業率警戒',
  recession: '🔴 Sahm Rule 觸發',
};

// Gauge ±1.0 sahm units covers every U.S. recession since 1959 — the
// 2020 COVID spike maxed out around +4 but is a censored outlier; the
// historic typical pre-recession reading is 0.5-1.0.
const GAUGE_MIN = -0.2;
const GAUGE_MAX = 1.0;

export interface UnrateHeadlineLabels {
  ruleTitle: string;
  ruleNote: string;
}

export function UnrateHeadlineExplainable({
  shortLabel,
  detail,
  labels,
}: {
  shortLabel: string;
  detail: Record<string, unknown>;
  labels: UnrateHeadlineLabels;
}): JSX.Element {
  const parsed = unrateDetailSchema.safeParse(detail);
  if (!parsed.success) return <span>{shortLabel}</span>;
  const d = parsed.data;
  const zone = classifyZone(d);
  return (
    <Explainable
      title={labels.ruleTitle}
      explanation={
        <RuleTable
          preface="Sahm Rule (Claudia Sahm 2019): 失業率 3 個月平均 − 過去 12 個月最低 ≥ 0.5 → 衰退已開始。自 1959 以來零次誤觸。"
          rows={[
            {
              condition: `Sahm < ${d.threshold_warning}`,
              result: '🟢 失業率穩定，無衰退訊號',
              current: zone === 'healthy',
            },
            {
              condition: `${d.threshold_warning} ≤ Sahm < ${d.threshold_trigger}`,
              result: '🟡 警戒區，距離觸發 < 0.20',
              current: zone === 'warning',
            },
            {
              condition: `Sahm ≥ ${d.threshold_trigger}`,
              result: '🔴 Sahm Rule 觸發 — 衰退已在發生',
              current: zone === 'recession',
            },
          ]}
          currentValueText={`你目前: 失業率 ${d.current_rate.toFixed(1)}% · Sahm = ${d.sahm_value >= 0 ? '+' : ''}${d.sahm_value.toFixed(2)} → ${ZONE_LABEL[zone]}`}
          note={labels.ruleNote}
        />
      }
    >
      {shortLabel}
    </Explainable>
  );
}

export function UnrateEnhancedDetail({
  detail,
}: {
  detail: Record<string, unknown>;
}): JSX.Element | null {
  const parsed = unrateDetailSchema.safeParse(detail);
  if (!parsed.success) return null;
  const d = parsed.data;
  const zone = classifyZone(d);

  const zones: ReadonlyArray<PositionGaugeZone> = [
    {
      upTo: d.threshold_warning,
      label: '健康',
      bg: 'bg-signal-green/30',
      text: 'text-signal-green',
    },
    {
      upTo: d.threshold_trigger,
      label: '警戒',
      bg: 'bg-amber-400/30',
      text: 'text-amber-700',
    },
    {
      upTo: GAUGE_MAX,
      label: '衰退',
      bg: 'bg-signal-red/30',
      text: 'text-signal-red',
    },
  ];

  return (
    <div className="flex flex-col gap-3 px-3 py-3 text-sm">
      <section
        aria-label="Sahm Rule 位置條"
        className="flex flex-col gap-2 text-xs"
      >
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h3 className="text-stone-500">Sahm 距離（觸發於 +0.50）</h3>
          <span className="text-stone-500">
            <span className="text-[10px] text-stone-400">Sahm</span>
            <span className="ml-1 font-mono tabular-nums text-stone-900">
              {d.sahm_value >= 0 ? '+' : ''}
              {d.sahm_value.toFixed(2)}
            </span>
            {d.sahm_distance_to_trigger !== undefined && (
              <>
                <span className="mx-1 text-stone-400">·</span>
                <span className="text-[10px] text-stone-400">距離觸發</span>
                <span className="ml-1 font-mono tabular-nums text-stone-700">
                  {d.sahm_distance_to_trigger >= 0 ? '+' : ''}
                  {d.sahm_distance_to_trigger.toFixed(2)}
                </span>
              </>
            )}
          </span>
        </div>
        <PositionGauge
          value={Math.max(GAUGE_MIN, Math.min(GAUGE_MAX, d.sahm_value))}
          min={GAUGE_MIN}
          max={GAUGE_MAX}
          zones={zones}
          ariaLabel={`Sahm 值 ${d.sahm_value.toFixed(2)},${ZONE_LABEL[zone]}`}
          highlightCurrentZone
        />
      </section>

      <TonePill
        zone={zone}
        sahmValue={d.sahm_value}
        sahmDistanceToTrigger={d.sahm_distance_to_trigger}
      />

      <section
        aria-label="失業率現況"
        className="flex flex-col gap-1 rounded-md border border-stone-200 bg-stone-50 px-3 py-2 text-xs"
      >
        <h3 className="text-stone-500">失業率現況</h3>
        <p className="text-stone-700">
          <span className="font-mono">當期</span>{' '}
          <span className="font-mono tabular-nums text-stone-900">
            {d.current_rate.toFixed(1)}%
          </span>
          <span className="mx-1 text-stone-400">·</span>
          <span className="font-mono">3MMA</span>{' '}
          <span className="font-mono tabular-nums text-stone-900">
            {d.three_month_avg.toFixed(2)}%
          </span>
          <span className="mx-1 text-stone-400">·</span>
          <span className="font-mono">12M 低點</span>{' '}
          <span className="font-mono tabular-nums text-stone-900">
            {d.twelve_month_low.toFixed(1)}%
          </span>
        </p>
      </section>
      <Watchpoints zone={zone} detail={d} />
    </div>
  );
}

function TonePill({
  zone,
  sahmValue,
  sahmDistanceToTrigger,
}: {
  zone: UnrateZone;
  sahmValue: number;
  sahmDistanceToTrigger: number | undefined;
}): JSX.Element {
  const tone =
    zone === 'recession'
      ? 'border-signal-red/40 bg-signal-red/10 text-signal-red'
      : zone === 'warning'
        ? 'border-amber-400/40 bg-amber-50 text-amber-700'
        : 'border-signal-green/40 bg-signal-green/10 text-signal-green';
  const distancePhrase =
    sahmDistanceToTrigger !== undefined
      ? `,距 Sahm 觸發 ${sahmDistanceToTrigger >= 0 ? '+' : ''}${sahmDistanceToTrigger.toFixed(2)}`
      : '';
  const summary =
    zone === 'recession'
      ? `🔴 Sahm Rule 觸發 — 衰退已在發生 (Sahm ${sahmValue >= 0 ? '+' : ''}${sahmValue.toFixed(2)})`
      : zone === 'warning'
        ? `🟡 失業率警戒 — 距離 Sahm 觸發 < 0.20${distancePhrase}`
        : `🟢 失業率穩定 — 無衰退訊號${distancePhrase}`;
  return (
    <section
      aria-label="失業率判讀"
      className={`flex items-center gap-2 rounded-md border px-3 py-2 text-xs ${tone}`}
    >
      <span className="font-medium">{summary}</span>
    </section>
  );
}

function buildWatchpoints(zone: UnrateZone, d: UnrateDetail): UnrateWatchpoint[] {
  if (zone === 'healthy') {
    return [
      { direction: 'up', threshold: d.threshold_warning, nextLabel: ZONE_LABEL.warning },
    ];
  }
  if (zone === 'warning') {
    return [
      { direction: 'down', threshold: d.threshold_warning, nextLabel: ZONE_LABEL.healthy },
      { direction: 'up', threshold: d.threshold_trigger, nextLabel: ZONE_LABEL.recession },
    ];
  }
  return [
    { direction: 'down', threshold: d.threshold_trigger, nextLabel: ZONE_LABEL.warning },
    { direction: 'down', threshold: d.threshold_warning, nextLabel: ZONE_LABEL.healthy },
  ];
}

function Watchpoints({
  zone,
  detail,
}: {
  zone: UnrateZone;
  detail: UnrateDetail;
}): JSX.Element {
  const points = buildWatchpoints(zone, detail);
  return (
    <section aria-label="Sahm 看點" className="flex flex-col gap-2 text-xs">
      <h3 className="text-stone-500">
        <Explainable
          title="看點生成規則"
          explanation={
            <RuleTable
              preface="依目前所在區塊決定要顯示哪些 Sahm 值轉換："
              rows={[
                {
                  condition: '🟢 健康 (Sahm < 0.30)',
                  result: '只看「Sahm 升至 0.30 → 警戒」',
                  current: zone === 'healthy',
                },
                {
                  condition: '🟡 警戒 (0.30 ≤ Sahm < 0.50)',
                  result: '雙向(跌至 0.30 → 健康 / 升至 0.50 → Sahm 觸發)',
                  current: zone === 'warning',
                },
                {
                  condition: '🔴 衰退 (Sahm ≥ 0.50)',
                  result: '兩條皆為「恢復條件」',
                  current: zone === 'recession',
                },
              ]}
              note="閾值 0.30 是「警戒前哨」,0.50 是 Sahm Rule 衰退觸發點。"
            />
          }
        >
          看點
        </Explainable>
        <span className="ml-1 text-stone-400">（觸發轉態勢的關鍵 Sahm 值）</span>
      </h3>
      <ul className="flex flex-col gap-1.5">
        {points.map((p) => (
          <li
            key={`${p.direction}-${p.threshold}`}
            className="flex flex-wrap items-center gap-2 rounded-md border border-stone-200 bg-stone-50 px-2 py-1.5"
          >
            <span className="text-stone-700">
              Sahm {p.direction === 'up' ? '升至' : '跌至'} +{p.threshold.toFixed(2)}
            </span>
            <span className="text-stone-400">→</span>
            <span className="text-stone-700">{p.nextLabel}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
