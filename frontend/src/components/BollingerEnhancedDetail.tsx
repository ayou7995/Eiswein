import { z } from 'zod';
import { Explainable, RuleTable } from './Explainable';
import { PositionGauge, type PositionGaugeZone } from './PositionGauge';

// Bollinger Bands detail emitted by `app/indicators/timing/bollinger.py`.
// `position` is normalised: 0 = lower band, 0.5 = middle (20MA),
// 1 = upper band. Values < 0 / > 1 indicate breakouts beyond the
// envelope. Detail shape stable since v1.0.0.
const bollingerDetailSchema = z.object({
  upper: z.number(),
  middle: z.number(),
  lower: z.number(),
  price: z.number(),
  position: z.number(),
  band_width: z.number(),
});

type BbDetail = z.infer<typeof bollingerDetailSchema>;
type BbSignal = 'breakout_up' | 'middle_upper' | 'middle_lower' | 'breakout_down';

function classifySignal(d: BbDetail): BbSignal {
  if (d.price > d.upper) return 'breakout_up';
  if (d.price < d.lower) return 'breakout_down';
  if (d.price >= d.middle) return 'middle_upper';
  return 'middle_lower';
}

const SIGNAL_LABEL: Record<BbSignal, string> = {
  breakout_up: '🔴 突破上軌（超買）',
  middle_upper: '🟡 中軌上方（偏強）',
  middle_lower: '🟡 中軌下方（偏弱）',
  breakout_down: '🟢 跌破下軌（超賣）',
};

// Gauge spans -0.2 ~ 1.2 to leave visual headroom for breakouts on
// either side. The marker clips to the edge for extreme values; the
// header inline shows the precise position number regardless.
const GAUGE_MIN = -0.2;
const GAUGE_MAX = 1.2;

// Bollinger semantics are mean-reverting: breaking the upper band is
// bearish (overbought, 紅), breaking the lower band is bullish
// (oversold, 綠). Mirrors RSI's inverted tone palette.
const ZONES: ReadonlyArray<PositionGaugeZone> = [
  { upTo: 0, label: '突破下軌', bg: 'bg-signal-green/30', text: 'text-signal-green' },
  { upTo: 0.5, label: '中軌下方', bg: 'bg-slate-700/40', text: 'text-slate-300' },
  { upTo: 1, label: '中軌上方', bg: 'bg-slate-600/40', text: 'text-slate-200' },
  { upTo: GAUGE_MAX, label: '突破上軌', bg: 'bg-signal-red/30', text: 'text-signal-red' },
];

export interface BollingerHeadlineLabels {
  ruleTitle: string;
  ruleNote: string;
}

export function BollingerHeadlineExplainable({
  shortLabel,
  detail,
  labels,
}: {
  shortLabel: string;
  detail: Record<string, unknown>;
  labels: BollingerHeadlineLabels;
}): JSX.Element {
  const parsed = bollingerDetailSchema.safeParse(detail);
  if (!parsed.success) return <span>{shortLabel}</span>;
  const d = parsed.data;
  const signal = classifySignal(d);
  return (
    <Explainable
      title={labels.ruleTitle}
      explanation={
        <RuleTable
          preface="布林通道 = 20 日 SMA ± 2σ。包含 95% 的價格波動（常態分布假設）。突破上下軌 → 價格進入「異常區」，**統計上會回歸均值**（mean reversion）。但強趨勢可能延著上/下軌走多日，需配合其他指標確認。"
          rows={[
            {
              condition: '收盤 > 上軌',
              result: '🔴 超買警示（拉回機會 > 追高）',
              current: signal === 'breakout_up',
            },
            {
              condition: '中軌 ≤ 收盤 ≤ 上軌',
              result: '🟡 中軌上方（偏強，無極端訊號）',
              current: signal === 'middle_upper',
            },
            {
              condition: '下軌 ≤ 收盤 < 中軌',
              result: '🟡 中軌下方（偏弱，無極端訊號）',
              current: signal === 'middle_lower',
            },
            {
              condition: '收盤 < 下軌',
              result: '🟢 超賣機會（反彈 > 續跌）',
              current: signal === 'breakout_down',
            },
          ]}
          currentValueText={`你目前: 價 ${d.price.toFixed(2)} / 下軌 ${d.lower.toFixed(2)} / 中軌 ${d.middle.toFixed(2)} / 上軌 ${d.upper.toFixed(2)} → 位置 ${(d.position * 100).toFixed(0)}% → ${SIGNAL_LABEL[signal]}`}
          note={labels.ruleNote}
        />
      }
    >
      {shortLabel}
    </Explainable>
  );
}

export function BollingerEnhancedDetail({
  detail,
}: {
  detail: Record<string, unknown>;
}): JSX.Element | null {
  const parsed = bollingerDetailSchema.safeParse(detail);
  if (!parsed.success) return null;
  const d = parsed.data;
  const signal = classifySignal(d);

  return (
    <div className="flex flex-col gap-3 px-3 py-3 text-sm">
      <PositionSection detail={d} />
      <Watchpoints detail={d} signal={signal} />
    </div>
  );
}

function PositionSection({ detail: d }: { detail: BbDetail }): JSX.Element {
  return (
    <section aria-label="布林通道帶內位置" className="flex flex-col gap-2 text-xs">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-slate-400">帶內位置（0 = 下軌，1 = 上軌）</h3>
        <span className="text-slate-400">
          <span className="text-[10px] text-slate-500">位置</span>
          <span className="ml-1 font-mono tabular-nums text-slate-100">
            {(d.position * 100).toFixed(0)}%
          </span>
          <span className="mx-1 text-slate-600">·</span>
          <span className="text-[10px] text-slate-500">帶寬</span>
          <span className="ml-1 font-mono tabular-nums text-slate-300">
            {d.band_width.toFixed(2)}
          </span>
        </span>
      </div>
      <PositionGauge
        value={Math.max(GAUGE_MIN, Math.min(GAUGE_MAX, d.position))}
        min={GAUGE_MIN}
        max={GAUGE_MAX}
        zones={ZONES}
        ariaLabel={`布林帶位置 ${(d.position * 100).toFixed(0)}%`}
        highlightCurrentZone
      />
    </section>
  );
}

interface BbWatchpoint {
  direction: 'up' | 'down';
  level: number;
  description: string;
}

function buildWatchpoints(d: BbDetail, signal: BbSignal): BbWatchpoint[] {
  // Map current signal to "what's the next state change?" — surface
  // both the upside and downside trigger so the user sees the band
  // boundaries that matter regardless of which way price moves.
  if (signal === 'breakout_up') {
    return [
      { direction: 'down', level: d.upper, description: '回到上軌內 → 解除超買' },
      { direction: 'down', level: d.middle, description: '跌回中軌 → 進入弱勢' },
    ];
  }
  if (signal === 'breakout_down') {
    return [
      { direction: 'up', level: d.lower, description: '回升上軌內 → 解除超賣' },
      { direction: 'up', level: d.middle, description: '回到中軌 → 進入強勢' },
    ];
  }
  if (signal === 'middle_upper') {
    return [
      { direction: 'up', level: d.upper, description: '突破上軌 → 超買警示' },
      { direction: 'down', level: d.middle, description: '跌回中軌下 → 轉弱' },
    ];
  }
  return [
    { direction: 'down', level: d.lower, description: '跌破下軌 → 超賣機會' },
    { direction: 'up', level: d.middle, description: '突破中軌 → 轉強' },
  ];
}

function Watchpoints({
  detail: d,
  signal,
}: {
  detail: BbDetail;
  signal: BbSignal;
}): JSX.Element {
  const points = buildWatchpoints(d, signal);
  return (
    <section aria-label="布林帶看點" className="flex flex-col gap-1.5 text-xs">
      <h3 className="text-slate-400">
        <Explainable
          title="看點生成規則"
          explanation={
            <RuleTable
              preface="依目前位置決定要顯示哪些「下一個狀態」的觸發價位："
              rows={[
                {
                  condition: '🔴 突破上軌',
                  result: '兩條皆為「降溫條件」（回到上軌內、跌回中軌）',
                  current: signal === 'breakout_up',
                },
                {
                  condition: '🟡 中軌上方',
                  result: '雙向（突破上軌 / 跌回中軌下）',
                  current: signal === 'middle_upper',
                },
                {
                  condition: '🟡 中軌下方',
                  result: '雙向（跌破下軌 / 突破中軌）',
                  current: signal === 'middle_lower',
                },
                {
                  condition: '🟢 跌破下軌',
                  result: '兩條皆為「恢復條件」（回升下軌內、回到中軌）',
                  current: signal === 'breakout_down',
                },
              ]}
              note="布林帶會隨股價動態變化，看點價位每天都會微幅滾動。"
            />
          }
        >
          看點
        </Explainable>
        <span className="ml-1 text-slate-500">（觸發轉態勢的關鍵價位）</span>
      </h3>
      <ul className="flex flex-col gap-1">
        {points.map((p, idx) => (
          <li
            key={`${p.direction}-${p.level.toFixed(2)}-${idx}`}
            className="flex flex-wrap items-center gap-2 rounded-md border border-slate-800 bg-slate-950/40 px-2 py-1"
          >
            <span className="text-slate-300">
              {p.direction === 'up' ? '價突破' : '價跌至'}{' '}
              <span className="font-mono tabular-nums text-slate-100">
                {p.level.toFixed(2)}
              </span>
            </span>
            <span className="text-slate-500">→</span>
            <span className="text-slate-300">{p.description}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
