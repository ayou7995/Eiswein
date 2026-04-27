import { z } from 'zod';
import { Explainable, RuleTable } from './Explainable';
import { PositionGauge, type PositionGaugeZone } from './PositionGauge';

// Volume anomaly detail emitted by `app/indicators/direction/volume_anomaly.py`.
// `price_change_pct` is a percentage (e.g. 1.23 == +1.23 %), not a decimal.
const volumeAnomalyDetailSchema = z.object({
  today_volume: z.number(),
  avg_volume_20d: z.number(),
  ratio: z.number(),
  spike: z.boolean(),
  price_change_pct: z.number(),
});

type VolumeDetail = z.infer<typeof volumeAnomalyDetailSchema>;
type VolumeSignal = 'spike_up' | 'spike_down' | 'spike_flat' | 'normal';

const SPIKE_THRESHOLD = 2.0;

function classifySignal(d: VolumeDetail): VolumeSignal {
  if (!d.spike) return 'normal';
  if (d.price_change_pct > 0) return 'spike_up';
  if (d.price_change_pct < 0) return 'spike_down';
  return 'spike_flat';
}

const SIGNAL_LABEL: Record<VolumeSignal, string> = {
  spike_up: '🟢 放量上漲',
  spike_down: '🔴 放量下跌',
  spike_flat: '🟡 放量但方向不明',
  normal: '🟡 量能正常',
};

const GAUGE_MIN = 0;
const GAUGE_MAX = 5;

// Volume itself is direction-neutral — colour zones use slate/amber/sky
// rather than the signal palette so they don't suggest bullish/bearish on
// their own. The price-direction badge below carries that context.
const ZONES: ReadonlyArray<PositionGaugeZone> = [
  { upTo: 1, label: '量縮', bg: 'bg-slate-700/40', text: 'text-slate-400' },
  { upTo: SPIKE_THRESHOLD, label: '正常', bg: 'bg-amber-400/20', text: 'text-amber-400' },
  { upTo: GAUGE_MAX, label: '放量', bg: 'bg-sky-500/30', text: 'text-sky-400' },
];

export interface VolumeAnomalyHeadlineLabels {
  ruleTitle: string;
  ruleNote: string;
}

export function VolumeAnomalyHeadlineExplainable({
  shortLabel,
  detail,
  labels,
}: {
  shortLabel: string;
  detail: Record<string, unknown>;
  labels: VolumeAnomalyHeadlineLabels;
}): JSX.Element {
  const parsed = volumeAnomalyDetailSchema.safeParse(detail);
  if (!parsed.success) return <span>{shortLabel}</span>;
  const d = parsed.data;
  const signal = classifySignal(d);
  return (
    <Explainable
      title={labels.ruleTitle}
      explanation={
        <RuleTable
          preface={`今日成交量 vs 過去 20 個交易日均量。Ratio = today / avg。spike 條件 = ratio ≥ ${SPIKE_THRESHOLD}×（O'Neil 派標準：機構動倉一定要量）。`}
          rows={[
            {
              condition: 'spike + 收漲',
              result: '🟢 放量上漲（機構積極買進）',
              current: signal === 'spike_up',
            },
            {
              condition: 'spike + 收跌',
              result: '🔴 放量下跌（機構積極賣出）',
              current: signal === 'spike_down',
            },
            {
              condition: 'spike + 平盤',
              result: '🟡 放量但方向不明',
              current: signal === 'spike_flat',
            },
            {
              condition: '無 spike (ratio < 2)',
              result: '🟡 量能正常',
              current: signal === 'normal',
            },
          ]}
          currentValueText={`你目前: ratio=${d.ratio.toFixed(2)}× (今日 ${formatVolume(d.today_volume)} / 20 日均量 ${formatVolume(d.avg_volume_20d)}) → ${SIGNAL_LABEL[signal]}`}
          note={labels.ruleNote}
        />
      }
    >
      {shortLabel}
    </Explainable>
  );
}

export function VolumeAnomalyEnhancedDetail({
  detail,
}: {
  detail: Record<string, unknown>;
}): JSX.Element | null {
  const parsed = volumeAnomalyDetailSchema.safeParse(detail);
  if (!parsed.success) return null;
  const d = parsed.data;

  return (
    <div className="flex flex-col gap-3 px-3 py-3 text-sm">
      <RatioSection detail={d} />
      <DirectionBadge detail={d} />
    </div>
  );
}

function RatioSection({ detail: d }: { detail: VolumeDetail }): JSX.Element {
  return (
    <section aria-label="量比位置條" className="flex flex-col gap-2 text-xs">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-slate-400">今日量比（vs 20 日均量，0–5×）</h3>
        <span className="text-slate-400">
          <span className="text-[10px] text-slate-500">今日</span>
          <span className="ml-1 font-mono tabular-nums text-slate-100">
            {formatVolume(d.today_volume)}
          </span>
          <span className="mx-1 text-slate-600">·</span>
          <span className="text-[10px] text-slate-500">20 日均</span>
          <span className="ml-1 font-mono tabular-nums text-slate-300">
            {formatVolume(d.avg_volume_20d)}
          </span>
          <span className="mx-1 text-slate-600">·</span>
          <span className="font-mono tabular-nums text-slate-100">
            {d.ratio.toFixed(2)}×
          </span>
        </span>
      </div>
      <PositionGauge
        value={Math.min(d.ratio, GAUGE_MAX)}
        min={GAUGE_MIN}
        max={GAUGE_MAX}
        zones={ZONES}
        ariaLabel={`今日量比 ${d.ratio.toFixed(2)}×`}
        highlightCurrentZone
      />
    </section>
  );
}

// Today's price direction is the *modifier* — volume alone doesn't tell
// you whether institutions are buying or selling, the close direction does.
// Mirrors the secondary-signal pattern (VIX trend pill / yield_spread badge).
function DirectionBadge({ detail: d }: { detail: VolumeDetail }): JSX.Element {
  const display = describeDirection(d);
  return (
    <section
      aria-label="今日價格方向"
      className={`flex items-center gap-2 rounded-md border px-3 py-2 text-xs ${display.tone}`}
    >
      <span aria-hidden="true">{display.emoji}</span>
      <Explainable
        title="價格方向解讀"
        explanation={
          <RuleTable
            preface="量是中性的；和今日價格方向結合才有「資金進/出」的解讀力。"
            rows={[
              {
                condition: '收漲 + 放量',
                result: '🟢 機構積極買進',
                current: d.spike && d.price_change_pct > 0,
              },
              {
                condition: '收跌 + 放量',
                result: '🔴 機構積極賣出',
                current: d.spike && d.price_change_pct < 0,
              },
              {
                condition: '收漲/跌 + 量能正常',
                result: '🟡 散戶輕量成交，無大資金介入訊號',
                current: !d.spike,
              },
              {
                condition: '收平 + 放量',
                result: '🟡 內部換手，方向不明',
                current: d.spike && d.price_change_pct === 0,
              },
            ]}
            note="O'Neil 派的 A/D Day 也是同一邏輯：量擴 + 漲 = 進貨；量擴 + 跌 = 出貨。"
          />
        }
      >
        <span>{display.label}</span>
      </Explainable>
    </section>
  );
}

function describeDirection(d: VolumeDetail): {
  emoji: string;
  label: string;
  tone: string;
} {
  const change = d.price_change_pct;
  if (d.spike && change > 0) {
    return {
      emoji: '🟢',
      label: `今日 ${formatChangePct(change)}（放量上漲，機構積極買進）`,
      tone: 'border-signal-green/40 bg-signal-green/10 text-signal-green',
    };
  }
  if (d.spike && change < 0) {
    return {
      emoji: '🔴',
      label: `今日 ${formatChangePct(change)}（放量下跌，機構積極賣出）`,
      tone: 'border-signal-red/40 bg-signal-red/10 text-signal-red',
    };
  }
  if (d.spike) {
    return {
      emoji: '🟡',
      label: `今日收平（放量但方向不明）`,
      tone: 'border-amber-400/40 bg-amber-400/10 text-amber-400',
    };
  }
  if (change > 0) {
    return {
      emoji: '⚪',
      label: `今日 ${formatChangePct(change)}（量能正常，無大資金訊號）`,
      tone: 'border-slate-700 bg-slate-950/40 text-slate-300',
    };
  }
  if (change < 0) {
    return {
      emoji: '⚪',
      label: `今日 ${formatChangePct(change)}（量能正常，無大資金訊號）`,
      tone: 'border-slate-700 bg-slate-950/40 text-slate-300',
    };
  }
  return {
    emoji: '⚪',
    label: '今日收平（量能正常）',
    tone: 'border-slate-700 bg-slate-950/40 text-slate-300',
  };
}

function formatVolume(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`;
  return n.toFixed(0);
}

function formatChangePct(n: number): string {
  return n >= 0 ? `+${n.toFixed(2)}%` : `${n.toFixed(2)}%`;
}
