import { z } from 'zod';
import { Explainable, RuleTable } from './Explainable';

// MACD detail emitted by `app/indicators/timing/macd.py`.
// Detail shape stable since v1.0.0: macd, signal, histogram, recent_cross
// (bullish/bearish/none — fired only when sign-change detected within
// the last `cross_lookback_bars` bars), cross_lookback_bars (currently 3).
const macdDetailSchema = z.object({
  macd: z.number(),
  signal: z.number(),
  histogram: z.number(),
  recent_cross: z.enum(['bullish', 'bearish', 'none']),
  cross_lookback_bars: z.number(),
});

type MacdDetail = z.infer<typeof macdDetailSchema>;
type MacdSubState = 'cross_up' | 'cross_down' | 'momentum_positive' | 'momentum_negative';

function classifySubState(d: MacdDetail): MacdSubState {
  if (d.recent_cross === 'bullish') return 'cross_up';
  if (d.recent_cross === 'bearish') return 'cross_down';
  return d.histogram > 0 ? 'momentum_positive' : 'momentum_negative';
}

const SUB_STATE_LABEL: Record<MacdSubState, string> = {
  cross_up: '🟢 MACD 金叉（動能反轉向上）',
  cross_down: '🔴 MACD 死叉（動能反轉向下）',
  momentum_positive: '🟡 柱狀正值（動能延續向上，無新交叉）',
  momentum_negative: '🟡 柱狀負值（動能延續向下，無新交叉）',
};

const SUB_STATE_TONE: Record<MacdSubState, string> = {
  cross_up: 'border-signal-green/40 bg-signal-green/10 text-signal-green',
  cross_down: 'border-signal-red/40 bg-signal-red/10 text-signal-red',
  momentum_positive: 'border-amber-400/40 bg-amber-400/10 text-amber-400',
  momentum_negative: 'border-amber-400/40 bg-amber-400/10 text-amber-400',
};

export interface MacdHeadlineLabels {
  ruleTitle: string;
  ruleNote: string;
}

export function MacdHeadlineExplainable({
  shortLabel,
  detail,
  labels,
}: {
  shortLabel: string;
  detail: Record<string, unknown>;
  labels: MacdHeadlineLabels;
}): JSX.Element {
  const parsed = macdDetailSchema.safeParse(detail);
  if (!parsed.success) return <span>{shortLabel}</span>;
  const d = parsed.data;
  const sub = classifySubState(d);
  return (
    <Explainable
      title={labels.ruleTitle}
      explanation={
        <RuleTable
          preface={`MACD = EMA(12) − EMA(26)；signal = EMA(9, MACD)；histogram = MACD − signal。MACD 線穿越 signal 線 = 「交叉」訊號。只有最近 ${d.cross_lookback_bars} 個交易日內的交叉才算「新訊號」 — 更早的交叉視為已被市場消化。`}
          rows={[
            {
              condition: `近 ${d.cross_lookback_bars} 日內 MACD 由下穿上 signal`,
              result: '🟢 金叉（動能轉強，關注買點）',
              current: sub === 'cross_up',
            },
            {
              condition: `近 ${d.cross_lookback_bars} 日內 MACD 由上穿下 signal`,
              result: '🔴 死叉（動能轉弱，關注賣點）',
              current: sub === 'cross_down',
            },
            {
              condition: '無新交叉，histogram > 0',
              result: '🟡 柱狀正值（多頭動能延續）',
              current: sub === 'momentum_positive',
            },
            {
              condition: '無新交叉，histogram ≤ 0',
              result: '🟡 柱狀負值（空頭動能延續）',
              current: sub === 'momentum_negative',
            },
          ]}
          currentValueText={`你目前: MACD ${d.macd.toFixed(3)} · signal ${d.signal.toFixed(3)} · histogram ${d.histogram >= 0 ? '+' : ''}${d.histogram.toFixed(3)} → ${SUB_STATE_LABEL[sub]}`}
          note={labels.ruleNote}
        />
      }
    >
      {shortLabel}
    </Explainable>
  );
}

export function MacdEnhancedDetail({
  detail,
}: {
  detail: Record<string, unknown>;
}): JSX.Element | null {
  const parsed = macdDetailSchema.safeParse(detail);
  if (!parsed.success) return null;
  const d = parsed.data;
  const sub = classifySubState(d);

  return (
    <div className="flex flex-col gap-3 px-3 py-3 text-sm">
      <StateBadge subState={sub} />
      <Watchpoints subState={sub} />
    </div>
  );
}

function StateBadge({ subState }: { subState: MacdSubState }): JSX.Element {
  const tone = SUB_STATE_TONE[subState];
  const label = SUB_STATE_LABEL[subState];
  return (
    <section
      aria-label="MACD 狀態"
      className={`flex items-center gap-2 rounded-md border px-3 py-2 text-xs ${tone}`}
    >
      <Explainable
        title="狀態解讀"
        explanation={
          <RuleTable
            preface="交叉訊號 vs 動能延續訊號的差異：交叉是「方向反轉」的決策點，柱狀正/負只是「現有方向繼續」的脈絡。"
            rows={[
              {
                condition: '近期金叉',
                result: '🟢 多空雙方剛換手，最近一次轉折偏多',
                current: subState === 'cross_up',
              },
              {
                condition: '近期死叉',
                result: '🔴 多空雙方剛換手，最近一次轉折偏空',
                current: subState === 'cross_down',
              },
              {
                condition: '柱狀正值（無交叉）',
                result: '🟡 多頭仍在主導，但無新訊號',
                current: subState === 'momentum_positive',
              },
              {
                condition: '柱狀負值（無交叉）',
                result: '🟡 空頭仍在主導，但無新訊號',
                current: subState === 'momentum_negative',
              },
            ]}
            note="MACD 是「事後型」指標：交叉發生後才確認，不能預測。但對「該停利還是該再加碼」這類問題很有幫助。"
          />
        }
      >
        <span>{label}</span>
      </Explainable>
    </section>
  );
}

interface MacdWatchpoint {
  description: string;
  result: string;
}

function buildWatchpoints(subState: MacdSubState): MacdWatchpoint[] {
  // Cross states already represent a transition — show what would
  // unwind it. Momentum states show what would tip into a new cross.
  if (subState === 'cross_up') {
    return [
      { description: 'histogram 翻負', result: '🟡 動能轉弱，金叉退化' },
      { description: 'MACD 重新跌破 signal', result: '🔴 死叉反轉' },
    ];
  }
  if (subState === 'cross_down') {
    return [
      { description: 'histogram 翻正', result: '🟡 動能轉強，死叉退化' },
      { description: 'MACD 重新突破 signal', result: '🟢 金叉反轉' },
    ];
  }
  if (subState === 'momentum_positive') {
    return [
      { description: 'histogram 持續擴張', result: '🟢 多頭動能加速（追多 OK）' },
      { description: 'histogram 縮小至 0', result: '🟡 死叉預警，等下一個交叉' },
    ];
  }
  return [
    { description: 'histogram 持續擴張（負方向）', result: '🔴 空頭動能加速' },
    { description: 'histogram 縮小至 0', result: '🟡 金叉預警，等下一個交叉' },
  ];
}

function Watchpoints({ subState }: { subState: MacdSubState }): JSX.Element {
  const points = buildWatchpoints(subState);
  return (
    <section aria-label="MACD 看點" className="flex flex-col gap-1.5 text-xs">
      <h3 className="text-slate-400">
        <Explainable
          title="看點生成規則"
          explanation={
            <RuleTable
              preface="MACD 沒有固定數值門檻（它是相對值）；看點以「狀態轉換」描述："
              rows={[
                {
                  condition: '🟢 近期金叉',
                  result: 'histogram 翻負或 MACD 跌破 signal → 退化',
                  current: subState === 'cross_up',
                },
                {
                  condition: '🔴 近期死叉',
                  result: 'histogram 翻正或 MACD 突破 signal → 退化',
                  current: subState === 'cross_down',
                },
                {
                  condition: '🟡 柱狀正/負（無交叉）',
                  result: 'histogram 擴張 = 加速；縮至 0 = 等下次交叉',
                  current:
                    subState === 'momentum_positive' || subState === 'momentum_negative',
                },
              ]}
              note="histogram 的擴張/收縮看圖最直觀，下方 MACD 走勢圖可確認。"
            />
          }
        >
          看點
        </Explainable>
        <span className="ml-1 text-slate-500">（histogram 動態）</span>
      </h3>
      <ul className="flex flex-col gap-1">
        {points.map((p) => (
          <li
            key={p.description}
            className="flex flex-wrap items-center gap-2 rounded-md border border-slate-800 bg-slate-950/40 px-2 py-1"
          >
            <span className="text-slate-300">{p.description}</span>
            <span className="text-slate-500">→</span>
            <span className="text-slate-300">{p.result}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
