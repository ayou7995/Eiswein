import { z } from 'zod';
import { Explainable, RuleTable } from './Explainable';

// Detail fields written by `app/indicators/market_regime/spx_ma.py`. The
// derived (cross-state / stretch / watchpoints) layer is computed here on
// the client so the prototype shows up immediately on existing snapshots —
// no daily_update re-run needed. If the backend later persists these
// derivations as canonical fields, this component can swap to read them
// without changing its public interface.
const baseDetailSchema = z.object({
  price: z.number(),
  ma50: z.number(),
  ma200: z.number(),
  price_vs_ma50_pct: z.number(),
  price_vs_ma200_pct: z.number(),
  golden_cross_10d: z.boolean(),
  death_cross_10d: z.boolean(),
});

type BaseDetail = z.infer<typeof baseDetailSchema>;

type Stretch = 'over_extended' | 'healthy' | 'pressing' | 'broken';
type CrossState =
  | 'golden_cross_recent'
  | 'death_cross_recent'
  | 'golden_cross_established'
  | 'death_cross_established';
type SignalTone = 'green' | 'yellow' | 'red';

interface Watchpoint {
  level: 'ma50' | 'ma200';
  price: number;
  direction: 'up' | 'down';
  next_signal: SignalTone;
}

const STRETCH_OVER_EXTENDED = 10.0;
const STRETCH_HEALTHY = 2.0;

function classifyStretch(pct: number): Stretch {
  if (pct < 0) return 'broken';
  if (pct < STRETCH_HEALTHY) return 'pressing';
  if (pct < STRETCH_OVER_EXTENDED) return 'healthy';
  return 'over_extended';
}

function classifyCrossState(d: BaseDetail): CrossState {
  if (d.golden_cross_10d) return 'golden_cross_recent';
  if (d.death_cross_10d) return 'death_cross_recent';
  return d.ma50 > d.ma200 ? 'golden_cross_established' : 'death_cross_established';
}

function classifySignal(d: BaseDetail): SignalTone {
  if (d.price > d.ma50 && d.price > d.ma200) return 'green';
  if (d.price >= d.ma200) return 'yellow';
  return 'red';
}

function buildWatchpoints(d: BaseDetail): Watchpoint[] {
  const signal = classifySignal(d);
  if (signal === 'green') {
    return [
      { level: 'ma50', price: d.ma50, direction: 'down', next_signal: 'yellow' },
      { level: 'ma200', price: d.ma200, direction: 'down', next_signal: 'red' },
    ];
  }
  if (signal === 'yellow') {
    return [
      { level: 'ma50', price: d.ma50, direction: 'up', next_signal: 'green' },
      { level: 'ma200', price: d.ma200, direction: 'down', next_signal: 'red' },
    ];
  }
  return [
    { level: 'ma200', price: d.ma200, direction: 'up', next_signal: 'yellow' },
    { level: 'ma50', price: d.ma50, direction: 'up', next_signal: 'green' },
  ];
}

const STRETCH_LABEL: Record<Stretch, string> = {
  over_extended: '過度延伸',
  healthy: '健康延伸',
  pressing: '壓線測試',
  broken: '已跌破',
};

// Over-extended uses amber (warning, not loss) because being too far above
// is a pullback risk, not a regime break.
const STRETCH_TONE: Record<Stretch, string> = {
  over_extended: 'text-amber-400',
  healthy: 'text-signal-green',
  pressing: 'text-amber-400',
  broken: 'text-signal-red',
};

const CROSS_STATE_DISPLAY: Record<
  CrossState,
  { emoji: string; label: string; tone: string }
> = {
  golden_cross_recent: {
    emoji: '🌟',
    label: '近 10 日黃金交叉（中期多頭起點）',
    tone: 'text-signal-green',
  },
  death_cross_recent: {
    emoji: '⚠️',
    label: '近 10 日死亡交叉（規則仍可能綠但結構轉弱）',
    tone: 'text-signal-red',
  },
  golden_cross_established: {
    emoji: '🟢',
    label: '黃金交叉態勢（50MA > 200MA，已成立）',
    tone: 'text-signal-green',
  },
  death_cross_established: {
    emoji: '🔴',
    label: '死亡交叉態勢（50MA < 200MA，已成立）',
    tone: 'text-signal-red',
  },
};

const SIGNAL_LABEL: Record<SignalTone, string> = {
  green: '🟢 多頭排列',
  yellow: '🟡 短期偏弱',
  red: '🔴 空頭趨勢',
};

const LEVEL_LABEL: Record<Watchpoint['level'], string> = {
  ma50: '50MA',
  ma200: '200MA',
};

// Renders the indicator's headline ("SPX 多頭排列" / 中期多頭、短期偏弱
// / 空頭趨勢) wrapped in an Explainable that exposes the 3-tier signal
// classification rule, with the current row highlighted. Used in the
// market regime list summary so users can hover/click the headline
// without expanding the row.
export function SpxMaHeadlineExplainable({
  shortLabel,
  detail,
}: {
  shortLabel: string;
  detail: Record<string, unknown>;
}): JSX.Element {
  const parsed = baseDetailSchema.safeParse(detail);
  if (!parsed.success) return <span>{shortLabel}</span>;
  const d = parsed.data;
  const signal = classifySignal(d);
  return (
    <Explainable
      title="SPX 紅黃綠燈規則"
      explanation={
        <RuleTable
          preface="收盤價對 50MA / 200MA 位置決定主訊號："
          rows={[
            {
              condition: 'close > 50MA 且 close > 200MA',
              result: '🟢 多頭排列',
              current: signal === 'green',
            },
            {
              condition: 'close ≥ 200MA 且 close ≤ 50MA',
              result: '🟡 中期多頭、短期偏弱',
              current: signal === 'yellow',
            },
            {
              condition: 'close < 200MA',
              result: '🔴 空頭趨勢',
              current: signal === 'red',
            },
          ]}
          currentValueText={`你目前: 收盤=${d.price.toFixed(2)}, 50MA=${d.ma50.toFixed(2)}, 200MA=${d.ma200.toFixed(2)}`}
          note="此燈號是市場態勢 4 票之 1（綠/紅/黃 → 進攻/防守/正常）；展開列可看更深入的距離尺標與看點。"
        />
      }
    >
      {shortLabel}
    </Explainable>
  );
}

export interface SpxMaEnhancedDetailProps {
  detail: Record<string, unknown>;
}

export function SpxMaEnhancedDetail({
  detail,
}: SpxMaEnhancedDetailProps): JSX.Element | null {
  const parsed = baseDetailSchema.safeParse(detail);
  if (!parsed.success) return null;
  const d = parsed.data;
  const stretch50 = classifyStretch(d.price_vs_ma50_pct);
  const stretch200 = classifyStretch(d.price_vs_ma200_pct);
  const points = buildWatchpoints(d);

  return (
    <div className="flex flex-col gap-4 px-3 py-3 text-sm">
      <DistanceGauges
        pct50={d.price_vs_ma50_pct}
        pct200={d.price_vs_ma200_pct}
        stretch50={stretch50}
        stretch200={stretch200}
      />
      <CrossStateRow detail={d} />
      <Watchpoints points={points} signal={classifySignal(d)} />
    </div>
  );
}

interface DistanceGaugesProps {
  pct50: number;
  pct200: number;
  stretch50: Stretch;
  stretch200: Stretch;
}

function DistanceGauges({
  pct50,
  pct200,
  stretch50,
  stretch200,
}: DistanceGaugesProps): JSX.Element {
  return (
    <section
      aria-label="收盤離 MA 距離"
      className="flex flex-col gap-2 text-xs"
    >
      <h3 className="text-slate-400">距離尺標</h3>
      <DistanceRow label="距 50MA" pct={pct50} stretch={stretch50} />
      <DistanceRow label="距 200MA" pct={pct200} stretch={stretch200} />
    </section>
  );
}

interface DistanceRowProps {
  label: string;
  pct: number;
  stretch: Stretch;
}

// Bar caps at 15% so over-extended values don't blow out layout.
const BAR_CAP_PCT = 15;

function DistanceRow({ label, pct, stretch }: DistanceRowProps): JSX.Element {
  const capped = Math.max(-BAR_CAP_PCT, Math.min(BAR_CAP_PCT, pct));
  const positive = capped >= 0;
  const widthFraction = Math.abs(capped) / BAR_CAP_PCT;
  const widthStyle = { width: `${widthFraction * 50}%` };
  return (
    <div className="grid grid-cols-[5rem_1fr_auto] items-center gap-2">
      <span className="text-slate-400">{label}</span>
      <div
        role="img"
        aria-label={`${label} ${pct.toFixed(2)}%`}
        className="relative h-2 w-full rounded-full bg-slate-800"
      >
        <span aria-hidden="true" className="absolute left-1/2 top-0 h-2 w-px bg-slate-600" />
        <span
          aria-hidden="true"
          style={widthStyle}
          className={`absolute top-0 h-2 rounded-full ${
            positive ? 'left-1/2' : 'right-1/2'
          } ${positive ? 'bg-signal-green/60' : 'bg-signal-red/60'}`}
        />
      </div>
      <span className={`tabular-nums ${STRETCH_TONE[stretch]}`}>
        {pct >= 0 ? '+' : ''}
        {pct.toFixed(2)}%
        <span className="ml-1 text-[11px] text-slate-500">
          (
          <Explainable
            title={`${label} 分類規則`}
            explanation={
              <RuleTable
                preface="收盤相對均線距離分為 4 級："
                rows={[
                  {
                    condition: '< 0%',
                    result: '已跌破 🔴',
                    current: stretch === 'broken',
                  },
                  {
                    condition: '0% ~ +2%',
                    result: '壓線測試 🟡',
                    current: stretch === 'pressing',
                  },
                  {
                    condition: '+2% ~ +10%',
                    result: '健康延伸 🟢',
                    current: stretch === 'healthy',
                  },
                  {
                    condition: '≥ +10%',
                    result: '過度延伸 🟡（拉回風險）',
                    current: stretch === 'over_extended',
                  },
                ]}
                currentValueText={`你目前 ${pct >= 0 ? '+' : ''}${pct.toFixed(2)}% → ${STRETCH_LABEL[stretch]}`}
                note="2% 與 10% 是 SPX-style 指數調的閾值；個股可能用其他閾值。"
              />
            }
          >
            {STRETCH_LABEL[stretch]}
          </Explainable>
          )
        </span>
      </span>
    </div>
  );
}

function CrossStateRow({ detail }: { detail: BaseDetail }): JSX.Element {
  const state = classifyCrossState(detail);
  const cross = CROSS_STATE_DISPLAY[state];
  return (
    <section
      aria-label="均線交叉態勢"
      className={`flex items-center gap-2 rounded-md border border-slate-800 bg-slate-950/40 px-3 py-2 text-xs ${cross.tone}`}
    >
      <span aria-hidden="true">{cross.emoji}</span>
      <Explainable
        title="均線交叉態勢規則"
        explanation={
          <RuleTable
            preface="50MA 與 200MA 的相對位置 + 是否近期才發生交叉，依優先順序判定："
            rows={[
              {
                condition: 'golden_cross_10d = true',
                result: '近 10 日黃金交叉 🌟',
                current: state === 'golden_cross_recent',
              },
              {
                condition: 'death_cross_10d = true',
                result: '近 10 日死亡交叉 ⚠️',
                current: state === 'death_cross_recent',
              },
              {
                condition: '皆無 + ma50 > ma200',
                result: '黃金交叉態勢已成立 🟢',
                current: state === 'golden_cross_established',
              },
              {
                condition: '皆無 + ma50 < ma200',
                result: '死亡交叉態勢已成立 🔴',
                current: state === 'death_cross_established',
              },
            ]}
            currentValueText={`你目前: ma50=${detail.ma50.toFixed(2)}, ma200=${detail.ma200.toFixed(2)}, 近期交叉=${detail.golden_cross_10d || detail.death_cross_10d ? '有' : '無'}`}
            note="近期交叉訊號永遠優先於已成立態勢。"
          />
        }
      >
        {cross.label}
      </Explainable>
    </section>
  );
}

function Watchpoints({
  points,
  signal,
}: {
  points: readonly Watchpoint[];
  signal: SignalTone;
}): JSX.Element {
  return (
    <section aria-label="未來看點" className="flex flex-col gap-2 text-xs">
      <h3 className="text-slate-400">
        <Explainable
          title="看點生成規則"
          explanation={
            <RuleTable
              preface="依目前主訊號決定要顯示哪 2 條轉態勢條件："
              rows={[
                {
                  condition: '🟢 多頭排列',
                  result: '兩條皆為「下方威脅」(守線)',
                  current: signal === 'green',
                },
                {
                  condition: '🟡 短期偏弱',
                  result: '雙向 (站回變綠 / 跌深變紅)',
                  current: signal === 'yellow',
                },
                {
                  condition: '🔴 空頭趨勢',
                  result: '兩條皆為「上方反彈條件」',
                  current: signal === 'red',
                },
              ]}
              note="每條看點的價格 = 對應 MA 的當前值。實際走勢可能略過某一檔（例如急殺直接從 GREEN 到 RED）。"
            />
          }
        >
          看點
        </Explainable>
        （觸發轉態勢的關鍵價位）
      </h3>
      <ul className="flex flex-col gap-1.5">
        {points.map((p) => (
          <li
            key={`${p.level}-${p.direction}`}
            className="flex flex-wrap items-center gap-2 rounded-md border border-slate-800 bg-slate-950/40 px-2 py-1.5"
          >
            <span className="text-slate-300">
              {p.direction === 'up' ? '站上' : '跌破'} {LEVEL_LABEL[p.level]}
            </span>
            <span className="font-mono tabular-nums text-slate-100">
              ${p.price.toFixed(2)}
            </span>
            <span className="text-slate-500">→</span>
            <span className="text-slate-300">{SIGNAL_LABEL[p.next_signal]}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
