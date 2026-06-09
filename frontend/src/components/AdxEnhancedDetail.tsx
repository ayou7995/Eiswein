import { z } from 'zod';
import { Explainable, RuleTable } from './Explainable';
import { PositionGauge, type PositionGaugeZone } from './PositionGauge';

// Per-ticker (and market-regime) ADX detail emitted by
// ``app/indicators/timing/adx.py`` + ``market_regime/spx_adx.py``.
// Detail shape stable since v2 Phase 2 (2026-06).
const adxDetailSchema = z.object({
  adx: z.number(),
  plus_di: z.number(),
  minus_di: z.number(),
  direction: z.enum(['up', 'down']),
  slope_5d: z.number().nullable().optional(),
  no_trend_threshold: z.number().optional().default(20),
  trend_threshold: z.number().optional().default(25),
  strong_trend_threshold: z.number().optional().default(40),
});

type AdxDetail = z.infer<typeof adxDetailSchema>;

// Display cap: ADX hits 100 in pathological cases (linear ramps in
// tests) but real-market ADX rarely sustains above 50. Capping the
// gauge at 60 keeps the zone bands visually meaningful — operators
// never need to distinguish 65 from 95.
const GAUGE_MIN = 0;
const GAUGE_MAX = 60;

const ZONES: ReadonlyArray<PositionGaugeZone> = [
  // ADX semantics: low = no edge to trust either side; high = a trend
  // exists, doesn't say which way. Green = "trend confirmed" is
  // intentionally the WIDE strong-trend band (25-40); the 40+ band
  // (極強) is tinted slightly darker to flag exhaustion risk.
  {
    upTo: 20,
    label: '盤整',
    bg: 'bg-amber-400/20',
    text: 'text-amber-700',
  },
  {
    upTo: 25,
    label: '未明朗',
    bg: 'bg-amber-400/30',
    text: 'text-amber-800',
  },
  {
    upTo: 40,
    label: '強趨勢',
    bg: 'bg-signal-green/30',
    text: 'text-signal-green',
  },
  {
    upTo: GAUGE_MAX,
    label: '極強',
    bg: 'bg-signal-green/40',
    text: 'text-emerald-800',
  },
];

export interface AdxHeadlineLabels {
  ruleTitle: string;
  ruleNote: string;
}

export function AdxHeadlineExplainable({
  shortLabel,
  detail,
  labels,
}: {
  shortLabel: string;
  detail: Record<string, unknown>;
  labels: AdxHeadlineLabels;
}): JSX.Element {
  const parsed = adxDetailSchema.safeParse(detail);
  if (!parsed.success) return <span>{shortLabel}</span>;
  const d = parsed.data;
  return (
    <Explainable
      title={labels.ruleTitle}
      explanation={
        <RuleTable
          preface="ADX (Wilder 1978) 衡量趨勢「強度」而非方向。+DI / -DI 各自計算正/負動能,DX = |+DI − -DI| / (+DI + -DI),ADX = 14 期 Wilder 平滑 DX。方向看 +DI vs -DI 誰大;強度看 ADX 本身。ADX 是「獨立的中期趨勢強度指標」— 跟其他指標分開讀,不是修飾器。"
          rows={[
            {
              condition: `ADX ≥ ${d.trend_threshold} 且未明顯下滑`,
              result: '🟢 強趨勢',
              current: d.adx >= d.trend_threshold && (d.slope_5d ?? 0) >= -0.5,
            },
            {
              condition: `ADX ≥ ${d.trend_threshold} 且明顯下滑`,
              result: '🟡 趨勢轉弱',
              current: d.adx >= d.trend_threshold && (d.slope_5d ?? 0) < -0.5,
            },
            {
              condition: `${d.no_trend_threshold} ≤ ADX < ${d.trend_threshold}`,
              result: '🟡 趨勢未明朗',
              current: d.adx >= d.no_trend_threshold && d.adx < d.trend_threshold,
            },
            {
              condition: `ADX < ${d.no_trend_threshold}`,
              result: '🟡 盤整',
              current: d.adx < d.no_trend_threshold,
            },
          ]}
          currentValueText={`你目前: ADX=${d.adx.toFixed(1)} · +DI=${d.plus_di.toFixed(1)} · -DI=${d.minus_di.toFixed(1)} · 方向 ${d.direction === 'up' ? '↑ 多頭' : '↓ 空頭'}`}
          note={labels.ruleNote}
        />
      }
    >
      {shortLabel}
    </Explainable>
  );
}

export function AdxEnhancedDetail({
  detail,
}: {
  detail: Record<string, unknown>;
}): JSX.Element | null {
  const parsed = adxDetailSchema.safeParse(detail);
  if (!parsed.success) return null;
  const d = parsed.data;
  const adxDisplay = Math.min(d.adx, GAUGE_MAX);
  return (
    <div className="flex flex-col gap-3 px-3 py-3 text-sm">
      <section aria-label="ADX 強度尺標" className="flex flex-col gap-2 text-xs">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h3 className="text-stone-500">趨勢強度(ADX 0-60)</h3>
          <span className="text-stone-500">
            <span className="text-[10px] text-stone-400">ADX</span>
            <span className="ml-1 font-mono tabular-nums text-stone-900">
              {d.adx.toFixed(1)}
            </span>
            <span className="mx-1 text-stone-400">·</span>
            <span className="text-[10px] text-stone-400">5 日斜率</span>
            <span className="ml-1 font-mono tabular-nums text-stone-700">
              {d.slope_5d !== null && d.slope_5d !== undefined
                ? d.slope_5d.toFixed(2)
                : '—'}
            </span>
          </span>
        </div>
        <PositionGauge
          value={adxDisplay}
          min={GAUGE_MIN}
          max={GAUGE_MAX}
          zones={ZONES}
          ariaLabel={`ADX ${d.adx.toFixed(1)}`}
          highlightCurrentZone
        />
      </section>

      <DirectionPill
        direction={d.direction}
        plusDi={d.plus_di}
        minusDi={d.minus_di}
      />
      <Watchpoints detail={d} />
    </div>
  );
}

function DirectionPill({
  direction,
  plusDi,
  minusDi,
}: {
  direction: 'up' | 'down';
  plusDi: number;
  minusDi: number;
}): JSX.Element {
  const tone =
    direction === 'up'
      ? 'border-signal-green/40 bg-signal-green/10 text-signal-green'
      : 'border-signal-red/40 bg-signal-red/10 text-signal-red';
  return (
    <section
      aria-label="方向 (+DI vs -DI)"
      className={`flex items-center gap-2 rounded-md border px-3 py-2 text-xs ${tone}`}
    >
      <span aria-hidden="true">{direction === 'up' ? '↑' : '↓'}</span>
      <Explainable
        title="方向判讀 (±DI)"
        explanation={
          <p className="leading-relaxed text-stone-700">
            +DI = 14 期向上動能,-DI = 14 期向下動能。+DI &gt; -DI 表示多頭目前佔優。ADX
            告訴你趨勢強度,±DI 告訴你方向 — 兩個結合才是完整訊號。
          </p>
        }
      >
        <span className="font-medium">
          {direction === 'up' ? '多頭佔優' : '空頭佔優'}
        </span>
      </Explainable>
      <span className="ml-auto text-stone-500">
        +DI {plusDi.toFixed(1)} · -DI {minusDi.toFixed(1)}
      </span>
    </section>
  );
}

function Watchpoints({ detail }: { detail: AdxDetail }): JSX.Element {
  const items: Array<{ trigger: string; outcome: string }> = [
    {
      trigger: `ADX 升破 ${detail.trend_threshold}`,
      outcome: '🟢 強趨勢確立,順勢追多/追空',
    },
    {
      trigger: `ADX 跌破 ${detail.no_trend_threshold}`,
      outcome: '🟡 盤整,切換到均值回歸策略',
    },
  ];
  const zone =
    detail.adx >= detail.trend_threshold
      ? 'strong'
      : detail.adx >= detail.no_trend_threshold
        ? 'ambiguous'
        : 'choppy';
  return (
    <section aria-label="ADX 看點" className="flex flex-col gap-2 text-xs">
      <h3 className="text-stone-500">
        <Explainable
          title="看點生成規則"
          explanation={
            <RuleTable
              preface="ADX 強弱兩條閾值,雙向都會切換到不同策略框架："
              rows={[
                {
                  condition: '🟢 強趨勢 (ADX ≥ 25)',
                  result: '只看「跌破 20 → 切均值回歸」',
                  current: zone === 'strong',
                },
                {
                  condition: '🟡 未明朗 (20 ≤ ADX < 25)',
                  result: '雙向 (升破 25 → 強趨勢 / 跌破 20 → 盤整)',
                  current: zone === 'ambiguous',
                },
                {
                  condition: '🟡 盤整 (ADX < 20)',
                  result: '只看「升破 25 → 強趨勢確立」',
                  current: zone === 'choppy',
                },
              ]}
              note="閾值 20 / 25 是業界 Wilder ADX 強趨勢/盤整分界。"
            />
          }
        >
          看點
        </Explainable>
        <span className="ml-1 text-stone-400">（觸發轉態勢的關鍵閾值）</span>
      </h3>
      <ul className="flex flex-col gap-1">
        {items.map((it) => (
          <li
            key={it.trigger}
            className="flex flex-wrap items-center gap-2 rounded-md border border-stone-200 bg-stone-50 px-2 py-1"
          >
            <span className="text-stone-700">{it.trigger}</span>
            <span className="text-stone-400">→</span>
            <span className="text-stone-700">{it.outcome}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
