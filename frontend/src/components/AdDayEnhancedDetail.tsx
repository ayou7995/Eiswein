import { z } from 'zod';
import { Explainable, RuleTable } from './Explainable';
import { PositionGauge, type PositionGaugeZone } from './PositionGauge';

// A/D Day detail emitted by `app/indicators/market_regime/ad_day.py`.
const adDayDetailSchema = z.object({
  accum_count: z.number().int(),
  distrib_count: z.number().int(),
  net: z.number().int(),
  window_days: z.number().int().optional().default(25),
});

type AdDayDetail = z.infer<typeof adDayDetailSchema>;
type AdDaySignal = 'inflow' | 'mixed' | 'outflow';

function classifySignal(d: AdDayDetail): AdDaySignal {
  if (d.net >= 3) return 'inflow';
  if (d.net <= -3) return 'outflow';
  return 'mixed';
}

const SIGNAL_LABEL: Record<AdDaySignal, string> = {
  inflow: '🟢 資金流入',
  mixed: '🟡 觀望',
  outflow: '🔴 資金流出',
};

const GAUGE_MIN = -10;
const GAUGE_MAX = 10;

const ZONES: ReadonlyArray<PositionGaugeZone> = [
  { upTo: -2.5, label: '資金流出', bg: 'bg-signal-red/30', text: 'text-signal-red' },
  { upTo: 2.5, label: '觀望', bg: 'bg-amber-400/30', text: 'text-amber-400' },
  { upTo: GAUGE_MAX, label: '資金流入', bg: 'bg-signal-green/30', text: 'text-signal-green' },
];

export interface AdDayHeadlineLabels {
  ruleTitle: string;
  ruleNote: string;
}

export function AdDayHeadlineExplainable({
  shortLabel,
  detail,
  labels,
}: {
  shortLabel: string;
  detail: Record<string, unknown>;
  labels: AdDayHeadlineLabels;
}): JSX.Element {
  const parsed = adDayDetailSchema.safeParse(detail);
  if (!parsed.success) return <span>{shortLabel}</span>;
  const d = parsed.data;
  const signal = classifySignal(d);
  return (
    <Explainable
      title={labels.ruleTitle}
      explanation={
        <RuleTable
          preface={`O'Neil 進貨/出貨日法。${d.window_days} 個交易日窗口，淨值 = 進貨日 - 出貨日。`}
          rows={[
            {
              condition: 'net ≥ +3',
              result: '🟢 資金流入（大資金 net 買進）',
              current: signal === 'inflow',
            },
            {
              condition: '|net| ≤ 2',
              result: '🟡 觀望（進出相近，無明確方向）',
              current: signal === 'mixed',
            },
            {
              condition: 'net ≤ -3',
              result: '🔴 資金流出（大資金 net 賣出）',
              current: signal === 'outflow',
            },
          ]}
          currentValueText={`你目前: 進貨 ${d.accum_count} 出貨 ${d.distrib_count} → 淨值 ${formatNet(d.net)} → ${SIGNAL_LABEL[signal]}`}
          note={labels.ruleNote}
        />
      }
    >
      {shortLabel}
    </Explainable>
  );
}

export function AdDayEnhancedDetail({
  detail,
}: {
  detail: Record<string, unknown>;
}): JSX.Element | null {
  const parsed = adDayDetailSchema.safeParse(detail);
  if (!parsed.success) return null;
  const d = parsed.data;
  const signal = classifySignal(d);
  const neutralCount = Math.max(0, d.window_days - d.accum_count - d.distrib_count);

  return (
    <div className="flex flex-col gap-3 px-3 py-3 text-sm">
      <PositionSection
        net={d.net}
        windowDays={d.window_days}
        accum={d.accum_count}
        distrib={d.distrib_count}
        neutral={neutralCount}
      />
      <Watchpoints signal={signal} />
    </div>
  );
}

function PositionSection({
  net,
  windowDays,
  accum,
  distrib,
  neutral,
}: {
  net: number;
  windowDays: number;
  accum: number;
  distrib: number;
  neutral: number;
}): JSX.Element {
  return (
    <section aria-label="A/D Day 累計位置" className="flex flex-col gap-2 text-xs">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-slate-400">{windowDays} 日累計（淨值 -10 ~ +10）</h3>
        <span className="text-slate-400">
          <span className="text-signal-green">🟢 進 {accum}</span>
          <span className="mx-1 text-slate-600">·</span>
          <span className="text-signal-red">🔴 出 {distrib}</span>
          <span className="mx-1 text-slate-600">·</span>
          <span className="text-slate-300">⚪ 中 {neutral}</span>
        </span>
      </div>
      <PositionGauge
        value={net}
        min={GAUGE_MIN}
        max={GAUGE_MAX}
        zones={ZONES}
        ariaLabel={`A/D Day ${windowDays} 日累計淨值 ${formatNet(net)}`}
        valueSuffix="淨值"
        highlightCurrentZone
      />
    </section>
  );
}

interface Watchpoint {
  direction: 'up' | 'down';
  threshold: number;
  nextSignal: AdDaySignal;
}

function buildWatchpoints(signal: AdDaySignal): Watchpoint[] {
  if (signal === 'inflow') {
    return [
      { direction: 'down', threshold: 2, nextSignal: 'mixed' },
      { direction: 'down', threshold: -3, nextSignal: 'outflow' },
    ];
  }
  if (signal === 'mixed') {
    return [
      { direction: 'up', threshold: 3, nextSignal: 'inflow' },
      { direction: 'down', threshold: -3, nextSignal: 'outflow' },
    ];
  }
  return [
    { direction: 'up', threshold: -2, nextSignal: 'mixed' },
    { direction: 'up', threshold: 3, nextSignal: 'inflow' },
  ];
}

function Watchpoints({ signal }: { signal: AdDaySignal }): JSX.Element {
  const points = buildWatchpoints(signal);
  return (
    <section aria-label="A/D Day 看點" className="flex flex-col gap-1.5 text-xs">
      <h3 className="text-slate-400">
        <Explainable
          title="看點生成規則"
          explanation={
            <RuleTable
              preface="依目前淨值區段決定要顯示哪些轉換條件："
              rows={[
                {
                  condition: '🟢 資金流入 (≥+3)',
                  result: '兩條皆為「降溫條件」(下方威脅)',
                  current: signal === 'inflow',
                },
                {
                  condition: '🟡 觀望 (-2~+2)',
                  result: '雙向（升至 +3 / 跌至 -3）',
                  current: signal === 'mixed',
                },
                {
                  condition: '🔴 資金流出 (≤-3)',
                  result: '兩條皆為「恢復條件」(上方門檻)',
                  current: signal === 'outflow',
                },
              ]}
              note="A/D Day 是滾動窗口：每天最舊的一筆滾出、新一筆滾入，所以淨值天天變動。"
            />
          }
        >
          看點
        </Explainable>
        <span className="ml-1 text-slate-500">（觸發轉態勢的關鍵淨值）</span>
      </h3>
      <ul className="flex flex-col gap-1">
        {points.map((p) => (
          <li
            key={`${p.direction}-${p.threshold}`}
            className="flex flex-wrap items-center gap-2 rounded-md border border-slate-800 bg-slate-950/40 px-2 py-1"
          >
            <span className="text-slate-300">
              {p.direction === 'up' ? '淨值升至' : '淨值跌至'} {formatNet(p.threshold)}
            </span>
            <span className="text-slate-500">→</span>
            <span className="text-slate-300">{SIGNAL_LABEL[p.nextSignal]}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function formatNet(n: number): string {
  return n > 0 ? `+${n}` : `${n}`;
}
