import { z } from 'zod';
import { Explainable, RuleTable } from './Explainable';
import { PositionGauge, type PositionGaugeZone } from './PositionGauge';

// Relative-strength detail emitted by `app/indicators/direction/relative_strength.py`.
// Values are absolute (decimal) returns: 0.05 == +5%.
const relativeStrengthDetailSchema = z.object({
  ticker_20d_return: z.number(),
  spx_20d_return: z.number(),
  diff: z.number(),
});

type RsDetail = z.infer<typeof relativeStrengthDetailSchema>;
type RsSignal = 'strong' | 'inline' | 'weak';

const STRONG_THRESHOLD = 0.02; // 2 %

function classifySignal(d: RsDetail): RsSignal {
  if (d.diff > STRONG_THRESHOLD) return 'strong';
  if (d.diff < -STRONG_THRESHOLD) return 'weak';
  return 'inline';
}

const SIGNAL_LABEL: Record<RsSignal, string> = {
  strong: '🟢 強於大盤',
  inline: '🟡 接近大盤',
  weak: '🔴 弱於大盤',
};

// Practical span — most stocks fluctuate within ±10 % of SPX over 20 days.
// Outliers clip to the gauge edge but still render with the precise number
// in the header inline.
const GAUGE_MIN = -0.1;
const GAUGE_MAX = 0.1;

const ZONES: ReadonlyArray<PositionGaugeZone> = [
  { upTo: -STRONG_THRESHOLD, label: '弱於', bg: 'bg-signal-red/30', text: 'text-signal-red' },
  { upTo: STRONG_THRESHOLD, label: '接近', bg: 'bg-amber-400/20', text: 'text-amber-400' },
  { upTo: GAUGE_MAX, label: '強於', bg: 'bg-signal-green/30', text: 'text-signal-green' },
];

export interface RelativeStrengthHeadlineLabels {
  ruleTitle: string;
  ruleNote: string;
}

export function RelativeStrengthHeadlineExplainable({
  shortLabel,
  detail,
  labels,
}: {
  shortLabel: string;
  detail: Record<string, unknown>;
  labels: RelativeStrengthHeadlineLabels;
}): JSX.Element {
  const parsed = relativeStrengthDetailSchema.safeParse(detail);
  if (!parsed.success) return <span>{shortLabel}</span>;
  const d = parsed.data;
  const signal = classifySignal(d);
  return (
    <Explainable
      title={labels.ruleTitle}
      explanation={
        <RuleTable
          preface={`相對強度 = 個股 20 日報酬 − SPX 20 日報酬。20 日 ≈ 1 個交易月，反映「最近一個月跑贏/跑輸大盤」。閾值 ±2% 來自 O'Neil 系統「mid-cap 月平均超額報酬」標竿。`}
          rows={[
            {
              condition: 'diff > +2%',
              result: '🟢 強於大盤（領漲類股）',
              current: signal === 'strong',
            },
            {
              condition: '|diff| ≤ 2%',
              result: '🟡 接近大盤（同步走勢）',
              current: signal === 'inline',
            },
            {
              condition: 'diff < -2%',
              result: '🔴 弱於大盤（落後類股）',
              current: signal === 'weak',
            },
          ]}
          currentValueText={`你目前: 個股 ${formatPct(d.ticker_20d_return)} / SPX ${formatPct(d.spx_20d_return)} → 差距 ${formatPct(d.diff)} → ${SIGNAL_LABEL[signal]}`}
          note={labels.ruleNote}
        />
      }
    >
      {shortLabel}
    </Explainable>
  );
}

export function RelativeStrengthEnhancedDetail({
  detail,
}: {
  detail: Record<string, unknown>;
}): JSX.Element | null {
  const parsed = relativeStrengthDetailSchema.safeParse(detail);
  if (!parsed.success) return null;
  const d = parsed.data;
  const signal = classifySignal(d);

  return (
    <div className="flex flex-col gap-3 px-3 py-3 text-sm">
      <PositionSection detail={d} />
      <Watchpoints signal={signal} />
    </div>
  );
}

function PositionSection({ detail: d }: { detail: RsDetail }): JSX.Element {
  return (
    <section aria-label="相對強度位置條" className="flex flex-col gap-2 text-xs">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-slate-400">差距位置（20 日報酬差，-10% ~ +10%）</h3>
        <span className="text-slate-400">
          <span className="text-[10px] text-slate-500">個股</span>
          <span className="ml-1 font-mono tabular-nums text-slate-100">
            {formatPct(d.ticker_20d_return)}
          </span>
          <span className="mx-1 text-slate-600">·</span>
          <span className="text-[10px] text-slate-500">SPX</span>
          <span className="ml-1 font-mono tabular-nums text-slate-300">
            {formatPct(d.spx_20d_return)}
          </span>
          <span className="mx-1 text-slate-600">·</span>
          <span className="text-[10px] text-slate-500">差距</span>
          <span className="ml-1 font-mono tabular-nums text-slate-100">
            {formatPct(d.diff)}
          </span>
        </span>
      </div>
      <PositionGauge
        value={Math.max(GAUGE_MIN, Math.min(GAUGE_MAX, d.diff))}
        min={GAUGE_MIN}
        max={GAUGE_MAX}
        zones={ZONES}
        ariaLabel={`相對強度差距 ${formatPct(d.diff)}`}
        highlightCurrentZone
      />
    </section>
  );
}

interface Watchpoint {
  direction: 'up' | 'down';
  threshold: number;
  nextSignal: RsSignal;
}

function buildWatchpoints(signal: RsSignal): Watchpoint[] {
  if (signal === 'strong') {
    return [
      { direction: 'down', threshold: STRONG_THRESHOLD, nextSignal: 'inline' },
      { direction: 'down', threshold: -STRONG_THRESHOLD, nextSignal: 'weak' },
    ];
  }
  if (signal === 'inline') {
    return [
      { direction: 'up', threshold: STRONG_THRESHOLD, nextSignal: 'strong' },
      { direction: 'down', threshold: -STRONG_THRESHOLD, nextSignal: 'weak' },
    ];
  }
  return [
    { direction: 'up', threshold: -STRONG_THRESHOLD, nextSignal: 'inline' },
    { direction: 'up', threshold: STRONG_THRESHOLD, nextSignal: 'strong' },
  ];
}

function Watchpoints({ signal }: { signal: RsSignal }): JSX.Element {
  const points = buildWatchpoints(signal);
  return (
    <section aria-label="相對強度看點" className="flex flex-col gap-1.5 text-xs">
      <h3 className="text-slate-400">
        <Explainable
          title="看點生成規則"
          explanation={
            <RuleTable
              preface="依目前差距位置決定要顯示哪些閾值轉換："
              rows={[
                {
                  condition: '🟢 強於大盤 (>+2%)',
                  result: '兩條皆為「降溫條件」(下方威脅)',
                  current: signal === 'strong',
                },
                {
                  condition: '🟡 接近大盤 (-2% ~ +2%)',
                  result: '雙向（升至 +2% / 跌至 -2%）',
                  current: signal === 'inline',
                },
                {
                  condition: '🔴 弱於大盤 (<-2%)',
                  result: '兩條皆為「恢復條件」(上方門檻)',
                  current: signal === 'weak',
                },
              ]}
              note="20 日窗口滾動：每天最舊的一筆滾出、新一筆滾入，差距值天天變動。"
            />
          }
        >
          看點
        </Explainable>
        <span className="ml-1 text-slate-500">（觸發轉態勢的關鍵差距）</span>
      </h3>
      <ul className="flex flex-col gap-1">
        {points.map((p) => (
          <li
            key={`${p.direction}-${p.threshold}`}
            className="flex flex-wrap items-center gap-2 rounded-md border border-slate-800 bg-slate-950/40 px-2 py-1"
          >
            <span className="text-slate-300">
              {p.direction === 'up' ? '差距升至' : '差距跌至'} {formatPct(p.threshold)}
            </span>
            <span className="text-slate-500">→</span>
            <span className="text-slate-300">{SIGNAL_LABEL[p.nextSignal]}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function formatPct(n: number): string {
  const pct = n * 100;
  return `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%`;
}
