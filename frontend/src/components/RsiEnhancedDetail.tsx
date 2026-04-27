import { z } from 'zod';
import { Explainable, RuleTable } from './Explainable';
import { PositionGauge, type PositionGaugeZone } from './PositionGauge';

// Per-ticker RSI(14) detail emitted by `app/indicators/direction/rsi.py`.
// Detail shape stable since v1.0.0.
const rsiDetailSchema = z.object({
  daily_rsi: z.number(),
  weekly_rsi: z.number().nullable().optional(),
});

type RsiDetail = z.infer<typeof rsiDetailSchema>;

// Five buckets — three colour outcomes once weekly confirmation is folded in.
type RsiSubState =
  | 'overbought_confirmed' // daily>70 AND weekly>70 → RED
  | 'overbought_short'     // daily>70 AND weekly≤70 → YELLOW (短線超買)
  | 'neutral'              // 30≤daily≤70           → YELLOW
  | 'oversold_short'       // daily<30 AND weekly≥30 → YELLOW (短線超賣)
  | 'oversold_confirmed';  // daily<30 AND weekly<30 → GREEN

function classifySubState(d: RsiDetail): RsiSubState {
  const daily = d.daily_rsi;
  const weekly = d.weekly_rsi ?? null;
  if (daily > 70 && weekly !== null && weekly > 70) return 'overbought_confirmed';
  if (daily > 70) return 'overbought_short';
  if (daily < 30 && weekly !== null && weekly < 30) return 'oversold_confirmed';
  if (daily < 30) return 'oversold_short';
  return 'neutral';
}

const SUB_STATE_LABEL: Record<RsiSubState, string> = {
  overbought_confirmed: '🔴 RSI 超買確認（拉回風險高）',
  overbought_short: '🟡 短線超買（週線未確認）',
  neutral: '🟡 RSI 中性',
  oversold_short: '🟡 短線超賣（週線未確認）',
  oversold_confirmed: '🟢 RSI 超賣確認（反彈機會）',
};

const GAUGE_MIN = 0;
const GAUGE_MAX = 100;

const ZONES: ReadonlyArray<PositionGaugeZone> = [
  // RSI semantics are inverted relative to price: oversold (bottom) = bullish
  // (green in Eiswein's tone palette), overbought (top) = bearish (red).
  { upTo: 30, label: '超賣', bg: 'bg-signal-green/30', text: 'text-signal-green' },
  { upTo: 70, label: '中性', bg: 'bg-amber-400/20', text: 'text-amber-400' },
  { upTo: GAUGE_MAX, label: '超買', bg: 'bg-signal-red/30', text: 'text-signal-red' },
];

export interface RsiHeadlineLabels {
  ruleTitle: string;
  ruleNote: string;
}

export function RsiHeadlineExplainable({
  shortLabel,
  detail,
  labels,
}: {
  shortLabel: string;
  detail: Record<string, unknown>;
  labels: RsiHeadlineLabels;
}): JSX.Element {
  const parsed = rsiDetailSchema.safeParse(detail);
  if (!parsed.success) return <span>{shortLabel}</span>;
  const d = parsed.data;
  const sub = classifySubState(d);
  const weekly = d.weekly_rsi ?? null;
  return (
    <Explainable
      title={labels.ruleTitle}
      explanation={
        <RuleTable
          preface="RSI = 100 − 100/(1+RS)，RS = 14 期平均漲幅 / 14 期平均跌幅（Wilder 1978 平滑遞推）。值域 0-100，>70 偏超買、<30 偏超賣。日 RSI 用最近 14 個交易日（≈3 週）— 短期動能；週 RSI 用最近 14 個週收盤（≈14 週 / 3 個月）— 中期動能。雙重確認：兩條都極端時才轉燈，避免單日雜訊。"
          rows={[
            {
              condition: '日 > 70 且 週 > 70',
              result: '🔴 超買確認',
              current: sub === 'overbought_confirmed',
            },
            {
              condition: '日 > 70 但週 ≤ 70',
              result: '🟡 短線超買（未確認）',
              current: sub === 'overbought_short',
            },
            {
              condition: '30 ≤ 日 ≤ 70',
              result: '🟡 中性',
              current: sub === 'neutral',
            },
            {
              condition: '日 < 30 但週 ≥ 30',
              result: '🟡 短線超賣（未確認）',
              current: sub === 'oversold_short',
            },
            {
              condition: '日 < 30 且 週 < 30',
              result: '🟢 超賣確認',
              current: sub === 'oversold_confirmed',
            },
          ]}
          currentValueText={`你目前: 日 RSI=${d.daily_rsi.toFixed(1)}, 週 RSI=${weekly !== null ? weekly.toFixed(1) : '—'} → ${SUB_STATE_LABEL[sub]}`}
          note={labels.ruleNote}
        />
      }
    >
      {shortLabel}
    </Explainable>
  );
}

export function RsiEnhancedDetail({
  detail,
}: {
  detail: Record<string, unknown>;
}): JSX.Element | null {
  const parsed = rsiDetailSchema.safeParse(detail);
  if (!parsed.success) return null;
  const d = parsed.data;
  const sub = classifySubState(d);

  return (
    <div className="flex flex-col gap-3 px-3 py-3 text-sm">
      <PositionSection daily={d.daily_rsi} weekly={d.weekly_rsi ?? null} />
      <WeeklyConfirmBadge daily={d.daily_rsi} weekly={d.weekly_rsi ?? null} />
      <Watchpoints sub={sub} />
    </div>
  );
}

function PositionSection({
  daily,
  weekly,
}: {
  daily: number;
  weekly: number | null;
}): JSX.Element {
  return (
    <section aria-label="RSI 日線位置條" className="flex flex-col gap-2 text-xs">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-slate-400">日 RSI 位置（0–100）</h3>
        <span className="text-slate-400">
          <span className="text-[10px] text-slate-500">日</span>
          <span className="ml-1 font-mono tabular-nums text-slate-100">
            {daily.toFixed(1)}
          </span>
          <span className="mx-1 text-slate-600">·</span>
          <span className="text-[10px] text-slate-500">週</span>
          <span className="ml-1 font-mono tabular-nums text-slate-300">
            {weekly !== null ? weekly.toFixed(1) : '—'}
          </span>
        </span>
      </div>
      <PositionGauge
        value={daily}
        min={GAUGE_MIN}
        max={GAUGE_MAX}
        zones={ZONES}
        ariaLabel={`日 RSI ${daily.toFixed(1)}`}
        highlightCurrentZone
      />
    </section>
  );
}

// Mirrors VIX's trend pill / yield_spread's inversion badge — surfaces the
// per-indicator "secondary signal". Here it's whether the weekly timeframe
// agrees with the daily — Sherry's "週線確認" pattern.
function WeeklyConfirmBadge({
  daily,
  weekly,
}: {
  daily: number;
  weekly: number | null;
}): JSX.Element {
  const display = describeWeekly(daily, weekly);
  return (
    <section
      aria-label="週線確認"
      className={`flex items-center gap-2 rounded-md border px-3 py-2 text-xs ${display.tone}`}
    >
      <span aria-hidden="true">{display.emoji}</span>
      <Explainable
        title="週線確認規則"
        explanation={
          <RuleTable
            preface="日 RSI 看短期（14 天）動能、週 RSI 看中期（14 週 / ≈3 個月）動能。日線易被單日波動推到極值區；週線時間窗長 ~5 倍，是過濾雜訊的標準做法。"
            rows={[
              {
                condition: '日線+週線都 > 70',
                result: '🔴 超買確認 — 拉回機率高',
                current: daily > 70 && weekly !== null && weekly > 70,
              },
              {
                condition: '日線+週線都 < 30',
                result: '🟢 超賣確認 — 反彈機率高',
                current: daily < 30 && weekly !== null && weekly < 30,
              },
              {
                condition: '日線極端但週線未跟進',
                result: '🟡 短線雜訊，等週線方向',
                current:
                  weekly !== null &&
                  ((daily > 70 && weekly <= 70) || (daily < 30 && weekly >= 30)),
              },
              {
                condition: '日線在 30–70 之間',
                result: '⚪ 中性區，無確認需求',
                current: daily >= 30 && daily <= 70,
              },
            ]}
            note="⚠️ 鈍化現象：強勢趨勢中日 RSI 容易連續數週停在 >70 或 <30 — 「碰到 70 就賣」會錯過大牛市、「碰到 30 就買」會接到下跌中刀。週線確認就是過濾這種雜訊的標準做法。"
          />
        }
      >
        <span>{display.label}</span>
      </Explainable>
    </section>
  );
}

function describeWeekly(
  daily: number,
  weekly: number | null,
): {
  emoji: string;
  label: string;
  tone: string;
} {
  if (weekly === null) {
    return {
      emoji: '⚪',
      label: '週 RSI 資料不足，無法確認',
      tone: 'border-slate-700 bg-slate-950/40 text-slate-300',
    };
  }
  if (daily > 70 && weekly > 70) {
    return {
      emoji: '🔴',
      label: `週 RSI ${weekly.toFixed(1)} > 70，與日線同步超買`,
      tone: 'border-signal-red/40 bg-signal-red/10 text-signal-red',
    };
  }
  if (daily < 30 && weekly < 30) {
    return {
      emoji: '🟢',
      label: `週 RSI ${weekly.toFixed(1)} < 30，與日線同步超賣`,
      tone: 'border-signal-green/40 bg-signal-green/10 text-signal-green',
    };
  }
  if (daily > 70) {
    return {
      emoji: '🟡',
      label: `週 RSI ${weekly.toFixed(1)} 未跟進日線超買，可能是短線雜訊`,
      tone: 'border-amber-400/40 bg-amber-400/10 text-amber-400',
    };
  }
  if (daily < 30) {
    return {
      emoji: '🟡',
      label: `週 RSI ${weekly.toFixed(1)} 未跟進日線超賣，可能是短線雜訊`,
      tone: 'border-amber-400/40 bg-amber-400/10 text-amber-400',
    };
  }
  return {
    emoji: '⚪',
    label: `週 RSI ${weekly.toFixed(1)}，日線在中性區無確認需求`,
    tone: 'border-slate-700 bg-slate-950/40 text-slate-300',
  };
}

interface Watchpoint {
  direction: 'up' | 'down';
  threshold: number;
  label: string;
}

function buildWatchpoints(sub: RsiSubState): Watchpoint[] {
  if (sub === 'overbought_confirmed' || sub === 'overbought_short') {
    return [
      {
        direction: 'down',
        threshold: 70,
        label: '日 RSI 跌回 70 → 🟡 中性',
      },
    ];
  }
  if (sub === 'oversold_confirmed' || sub === 'oversold_short') {
    return [
      {
        direction: 'up',
        threshold: 30,
        label: '日 RSI 站回 30 → 🟡 中性',
      },
    ];
  }
  return [
    {
      direction: 'up',
      threshold: 70,
      label: '日 RSI 站上 70 → 🟡 短線超買',
    },
    {
      direction: 'down',
      threshold: 30,
      label: '日 RSI 跌破 30 → 🟡 短線超賣',
    },
  ];
}

function Watchpoints({ sub }: { sub: RsiSubState }): JSX.Element {
  const points = buildWatchpoints(sub);
  return (
    <section aria-label="RSI 看點" className="flex flex-col gap-1.5 text-xs">
      <h3 className="text-slate-400">
        <Explainable
          title="看點生成規則"
          explanation={
            <RuleTable
              preface="依目前日 RSI 區段顯示對應的轉換閾值。週線確認另外在上方 badge 呈現。"
              rows={[
                {
                  condition: '日 RSI > 70',
                  result: '看「跌回 70」回到中性',
                  current: sub === 'overbought_short' || sub === 'overbought_confirmed',
                },
                {
                  condition: '日 RSI 在 30–70',
                  result: '雙向（站上 70 / 跌破 30）',
                  current: sub === 'neutral',
                },
                {
                  condition: '日 RSI < 30',
                  result: '看「站回 30」回到中性',
                  current: sub === 'oversold_short' || sub === 'oversold_confirmed',
                },
              ]}
              note="閾值 30 / 70 是 RSI 標準。Wilder 1978 原書定義。"
            />
          }
        >
          看點
        </Explainable>
        <span className="ml-1 text-slate-500">（觸發轉態勢的關鍵 RSI 值）</span>
      </h3>
      <ul className="flex flex-col gap-1">
        {points.map((p) => (
          <li
            key={`${p.direction}-${p.threshold}`}
            className="rounded-md border border-slate-800 bg-slate-950/40 px-2 py-1 text-slate-300"
          >
            {p.label}
          </li>
        ))}
      </ul>
    </section>
  );
}
