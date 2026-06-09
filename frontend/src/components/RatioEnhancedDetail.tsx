import { z } from 'zod';
import { Explainable, RuleTable } from './Explainable';
import { PositionGauge, type PositionGaugeZone } from './PositionGauge';

// Shared anatomy for cross-asset / breadth ratio indicators (rsp_spy,
// hyg_ief, and any future analogue). The shape is intentionally simple:
// a ratio number + a 20-day slope expressed as percent. Both reach the
// same green/yellow/red verdict from the same threshold semantics, so
// the EnhancedDetail body is the same — only the labels differ.

const ratioDetailSchema = z.object({
  ratio: z.number(),
  slope_pct_per_day: z.number(),
  slope_20d_pct: z.number(),
  lookback_days: z.number().optional().default(20),
});

// Two legs (numerator / denominator) — rsp_close + spy_close for
// rsp_spy; hyg_close + ief_close for hyg_ief. We pass them as labelled
// props rather than encode them in the Zod schema so this component
// can serve both indicators (and any future ratio pair) without a
// schema change per addition.

export interface RatioHeadlineLabels {
  ruleTitle: string;
  ruleNote: string;
  preface: string;
  greenLabel: string; // e.g. "🟢 廣度健康"
  redLabel: string; // e.g. "🔴 窄漲警示"
  yellowLabel: string; // e.g. "🟡 廣度持平"
  ratioName: string; // e.g. "RSP/SPY"
}

export function RatioHeadlineExplainable({
  shortLabel,
  detail,
  labels,
}: {
  shortLabel: string;
  detail: Record<string, unknown>;
  labels: RatioHeadlineLabels;
}): JSX.Element {
  const parsed = ratioDetailSchema.safeParse(detail);
  if (!parsed.success) return <span>{shortLabel}</span>;
  const d = parsed.data;
  return (
    <Explainable
      title={labels.ruleTitle}
      explanation={
        <RuleTable
          preface={labels.preface}
          rows={[
            {
              condition: `${labels.ratioName} 20D 斜率 ≥ +1%`,
              result: labels.greenLabel,
              current: d.slope_pct_per_day >= 0.05,
            },
            {
              condition: `${labels.ratioName} 20D 斜率 ≤ -1%`,
              result: labels.redLabel,
              current: d.slope_pct_per_day <= -0.05,
            },
            {
              condition: `${labels.ratioName} 20D 斜率 在 ±1% 之間`,
              result: labels.yellowLabel,
              current:
                d.slope_pct_per_day > -0.05 && d.slope_pct_per_day < 0.05,
            },
          ]}
          currentValueText={`你目前: ${labels.ratioName}=${d.ratio.toFixed(4)} · 20 日斜率 ${d.slope_20d_pct >= 0 ? '+' : ''}${d.slope_20d_pct.toFixed(2)}%`}
          note={labels.ruleNote}
        />
      }
    >
      {shortLabel}
    </Explainable>
  );
}

export interface RatioEnhancedDetailLabels {
  // Display name for the numerator + denominator legs in the bottom card.
  numeratorLabel: string; // e.g. "RSP", "HYG"
  denominatorLabel: string; // e.g. "SPY", "IEF"
  // Detail-dict keys for the leg closes.
  numeratorKey: string; // "rsp_close" / "hyg_close"
  denominatorKey: string; // "spy_close" / "ief_close"
  // Headline tone copy.
  greenSummary: string; // "🟢 上升 — 信號偏多"
  redSummary: string; // "🔴 下降 — 信號偏空"
  yellowSummary: string; // "🟡 持平"
  // Watchpoint copy — short single-character zone labels for the
  // "突破 / 跌破" callouts. Mirrors the existing ratioName so the prose
  // reads naturally ("RSP/SPY 20D 斜率 突破 +0.05%/日 → 🟢 上升").
  ratioName: string; // "RSP/SPY", "HYG/IEF"
  greenZoneLabel: string; // "🟢 上升 (廣度健康)"
  redZoneLabel: string; // "🔴 下降 (信用利差擴大)"
  yellowZoneLabel: string; // "🟡 持平"
}

// Gauge spans ±2% per day (i.e. ±40% over 20 days), well beyond the
// ±1% threshold that triggers GREEN/RED so the marker has room to land
// near either threshold without sitting on the edge.
const GAUGE_RANGE = 2;

const ZONES: ReadonlyArray<PositionGaugeZone> = [
  {
    upTo: -0.05,
    label: '下降',
    bg: 'bg-signal-red/30',
    text: 'text-signal-red',
  },
  {
    upTo: 0.05,
    label: '持平',
    bg: 'bg-stone-200',
    text: 'text-stone-700',
  },
  {
    upTo: GAUGE_RANGE,
    label: '上升',
    bg: 'bg-signal-green/30',
    text: 'text-signal-green',
  },
];

export function RatioEnhancedDetail({
  detail,
  labels,
}: {
  detail: Record<string, unknown>;
  labels: RatioEnhancedDetailLabels;
}): JSX.Element | null {
  const parsed = ratioDetailSchema.safeParse(detail);
  if (!parsed.success) return null;
  const d = parsed.data;
  const numerator = readNumber(detail, labels.numeratorKey);
  const denominator = readNumber(detail, labels.denominatorKey);
  // Clamp slope to gauge range so a freak day doesn't push the marker
  // off-screen — the actual value still shows in the header.
  const slopeDisplay = Math.max(
    -GAUGE_RANGE,
    Math.min(GAUGE_RANGE, d.slope_pct_per_day),
  );
  return (
    <div className="flex flex-col gap-3 px-3 py-3 text-sm">
      <section
        aria-label="20 日斜率位置條"
        className="flex flex-col gap-2 text-xs"
      >
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h3 className="text-stone-500">
            20 日斜率（% / 日,顯示 ±2% 區間）
          </h3>
          <span className="text-stone-500">
            <span className="text-[10px] text-stone-400">每日</span>
            <span className="ml-1 font-mono tabular-nums text-stone-900">
              {d.slope_pct_per_day >= 0 ? '+' : ''}
              {d.slope_pct_per_day.toFixed(3)}%
            </span>
            <span className="mx-1 text-stone-400">·</span>
            <span className="text-[10px] text-stone-400">20 日累計</span>
            <span className="ml-1 font-mono tabular-nums text-stone-700">
              {d.slope_20d_pct >= 0 ? '+' : ''}
              {d.slope_20d_pct.toFixed(2)}%
            </span>
          </span>
        </div>
        <PositionGauge
          value={slopeDisplay}
          min={-GAUGE_RANGE}
          max={GAUGE_RANGE}
          zones={ZONES}
          ariaLabel={`斜率 ${d.slope_pct_per_day.toFixed(3)}% / 日`}
          highlightCurrentZone
        />
      </section>

      <TonePill
        slopePctPerDay={d.slope_pct_per_day}
        greenSummary={labels.greenSummary}
        redSummary={labels.redSummary}
        yellowSummary={labels.yellowSummary}
      />
      <LegsPanel
        numerator={numerator}
        denominator={denominator}
        numeratorLabel={labels.numeratorLabel}
        denominatorLabel={labels.denominatorLabel}
        ratio={d.ratio}
      />
      <Watchpoints slopePctPerDay={d.slope_pct_per_day} labels={labels} />
    </div>
  );
}

type RatioZone = 'down' | 'flat' | 'up';

function classifyRatioZone(slopePctPerDay: number): RatioZone {
  if (slopePctPerDay >= 0.05) return 'up';
  if (slopePctPerDay <= -0.05) return 'down';
  return 'flat';
}

interface RatioWatchpoint {
  direction: 'up' | 'down';
  threshold: number; // slope_pct_per_day threshold (e.g. 0.05)
  nextLabel: string;
}

function buildRatioWatchpoints(
  zone: RatioZone,
  labels: RatioEnhancedDetailLabels,
): RatioWatchpoint[] {
  if (zone === 'up') {
    return [
      { direction: 'down', threshold: 0.05, nextLabel: labels.yellowZoneLabel },
    ];
  }
  if (zone === 'down') {
    return [
      { direction: 'up', threshold: -0.05, nextLabel: labels.yellowZoneLabel },
    ];
  }
  return [
    { direction: 'down', threshold: -0.05, nextLabel: labels.redZoneLabel },
    { direction: 'up', threshold: 0.05, nextLabel: labels.greenZoneLabel },
  ];
}

function Watchpoints({
  slopePctPerDay,
  labels,
}: {
  slopePctPerDay: number;
  labels: RatioEnhancedDetailLabels;
}): JSX.Element {
  const zone = classifyRatioZone(slopePctPerDay);
  const points = buildRatioWatchpoints(zone, labels);
  return (
    <section aria-label="比率看點" className="flex flex-col gap-2 text-xs">
      <h3 className="text-stone-500">
        <Explainable
          title="看點生成規則"
          explanation={
            <RuleTable
              preface="依目前所在區塊決定要顯示哪些斜率轉換："
              rows={[
                {
                  condition: `${labels.ratioName} 20D 斜率 ≥ +0.05%/日`,
                  result: `${labels.greenZoneLabel}`,
                  current: zone === 'up',
                },
                {
                  condition: `${labels.ratioName} 20D 斜率 在 ±0.05%/日 之間`,
                  result: `${labels.yellowZoneLabel}`,
                  current: zone === 'flat',
                },
                {
                  condition: `${labels.ratioName} 20D 斜率 ≤ -0.05%/日`,
                  result: `${labels.redZoneLabel}`,
                  current: zone === 'down',
                },
              ]}
              note="0.05%/日 ≈ 1%/20D。短期內小於此幅度視為持平,不算結構性轉折。"
            />
          }
        >
          看點
        </Explainable>
        <span className="ml-1 text-stone-400">（觸發轉態勢的關鍵斜率）</span>
      </h3>
      <ul className="flex flex-col gap-1.5">
        {points.map((p) => (
          <li
            key={`${p.direction}-${p.threshold}`}
            className="flex flex-wrap items-center gap-2 rounded-md border border-stone-200 bg-stone-50 px-2 py-1.5"
          >
            <span className="text-stone-700">
              斜率 {p.direction === 'up' ? '突破' : '跌破'}{' '}
              {p.threshold >= 0 ? '+' : ''}
              {p.threshold.toFixed(2)}%/日
            </span>
            <span className="text-stone-400">→</span>
            <span className="text-stone-700">{p.nextLabel}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function readNumber(detail: Record<string, unknown>, key: string): number | null {
  const v = detail[key];
  return typeof v === 'number' && Number.isFinite(v) ? v : null;
}

function TonePill({
  slopePctPerDay,
  greenSummary,
  redSummary,
  yellowSummary,
}: {
  slopePctPerDay: number;
  greenSummary: string;
  redSummary: string;
  yellowSummary: string;
}): JSX.Element {
  const tone =
    slopePctPerDay >= 0.05
      ? 'border-signal-green/40 bg-signal-green/10 text-signal-green'
      : slopePctPerDay <= -0.05
        ? 'border-signal-red/40 bg-signal-red/10 text-signal-red'
        : 'border-amber-400/40 bg-amber-50 text-amber-700';
  const label =
    slopePctPerDay >= 0.05
      ? greenSummary
      : slopePctPerDay <= -0.05
        ? redSummary
        : yellowSummary;
  return (
    <section
      aria-label="趨勢判讀"
      className={`flex items-center gap-2 rounded-md border px-3 py-2 text-xs ${tone}`}
    >
      <span className="font-medium">{label}</span>
    </section>
  );
}

function LegsPanel({
  numerator,
  denominator,
  numeratorLabel,
  denominatorLabel,
  ratio,
}: {
  numerator: number | null;
  denominator: number | null;
  numeratorLabel: string;
  denominatorLabel: string;
  ratio: number;
}): JSX.Element {
  return (
    <section
      aria-label="兩 ETF 當前價格"
      className="flex flex-col gap-1 rounded-md border border-stone-200 bg-stone-50 px-3 py-2 text-xs"
    >
      <h3 className="text-stone-500">兩支 ETF 當前價格</h3>
      <p className="text-stone-700">
        <span className="font-mono">{numeratorLabel}</span>{' '}
        <span className="font-mono text-stone-900">
          ${numerator != null ? numerator.toFixed(2) : '—'}
        </span>{' '}
        <span className="text-stone-400">/</span>{' '}
        <span className="font-mono">{denominatorLabel}</span>{' '}
        <span className="font-mono text-stone-900">
          ${denominator != null ? denominator.toFixed(2) : '—'}
        </span>{' '}
        <span className="mx-1 text-stone-400">=</span>{' '}
        <span className="font-mono text-stone-900">{ratio.toFixed(4)}</span>
      </p>
    </section>
  );
}
