import { z } from 'zod';
import { Explainable, RuleTable } from './Explainable';
import { PositionGauge, type PositionGaugeZone } from './PositionGauge';

// Per-ticker ATR detail emitted by ``app/indicators/timing/atr.py``.
// Detail shape stable since v2 Phase 2 (2026-06).
const atrDetailSchema = z.object({
  atr: z.number(),
  atr_pct: z.number(),
  close: z.number(),
  today_tr: z.number().nullable(),
  today_vs_atr: z.number().nullable(),
  calm_threshold_pct: z.number().optional().default(1.5),
  elevated_threshold_pct: z.number().optional().default(3.5),
});

// Display cap: most large-caps live in 0.5-3% ATR. Capping the gauge at
// 6% keeps the calm / elevated / high bands visually meaningful — a stock
// at 12% ATR is hyper-volatile, but the gauge needs only to communicate
// "definitely in the red band" not the exact magnitude.
const GAUGE_MIN = 0;
const GAUGE_MAX = 6;

const ZONES: ReadonlyArray<PositionGaugeZone> = [
  {
    upTo: 1.5,
    label: '平靜',
    bg: 'bg-signal-green/30',
    text: 'text-signal-green',
  },
  {
    upTo: 3.5,
    label: '正常偏上',
    bg: 'bg-amber-400/20',
    text: 'text-amber-700',
  },
  {
    upTo: GAUGE_MAX,
    label: '偏高',
    bg: 'bg-signal-red/30',
    text: 'text-signal-red',
  },
];

export interface AtrHeadlineLabels {
  ruleTitle: string;
  ruleNote: string;
}

export function AtrHeadlineExplainable({
  shortLabel,
  detail,
  labels,
}: {
  shortLabel: string;
  detail: Record<string, unknown>;
  labels: AtrHeadlineLabels;
}): JSX.Element {
  const parsed = atrDetailSchema.safeParse(detail);
  if (!parsed.success) return <span>{shortLabel}</span>;
  const d = parsed.data;
  return (
    <Explainable
      title={labels.ruleTitle}
      explanation={
        <RuleTable
          preface="ATR (Wilder 1978) 是日內真實波動範圍的 14 期平均,包含跳空缺口(取 max(H-L, |H-prevC|, |L-prevC|))。以 % of close 標準化後跨股可比。ATR 不分多空,RED 代表「波動高,部位要縮、停損要緊」,不是「賣出」。停損公式:close − 2 × ATR — 比固定 % 停損更尊重每支股票自己的個性。"
          rows={[
            {
              condition: `ATR% < ${d.calm_threshold_pct}%`,
              result: '🟢 平靜 — 正常部位,2 ATR 停損夠寬',
              current: d.atr_pct < d.calm_threshold_pct,
            },
            {
              condition: `${d.calm_threshold_pct}% ≤ ATR% < ${d.elevated_threshold_pct}%`,
              result: '🟡 正常偏上 — 留意 sizing',
              current:
                d.atr_pct >= d.calm_threshold_pct &&
                d.atr_pct < d.elevated_threshold_pct,
            },
            {
              condition: `ATR% ≥ ${d.elevated_threshold_pct}%`,
              result: '🔴 波動偏高 — 縮 size、停損調緊',
              current: d.atr_pct >= d.elevated_threshold_pct,
            },
          ]}
          currentValueText={`你目前: ATR=${d.atr.toFixed(2)} (${d.atr_pct.toFixed(2)}% of ${d.close.toFixed(2)}) · 2 ATR 停損距離 ≈ ${(d.atr * 2).toFixed(2)}`}
          note={labels.ruleNote}
        />
      }
    >
      {shortLabel}
    </Explainable>
  );
}

export function AtrEnhancedDetail({
  detail,
}: {
  detail: Record<string, unknown>;
}): JSX.Element | null {
  const parsed = atrDetailSchema.safeParse(detail);
  if (!parsed.success) return null;
  const d = parsed.data;
  const pctDisplay = Math.min(d.atr_pct, GAUGE_MAX);
  return (
    <div className="flex flex-col gap-3 px-3 py-3 text-sm">
      <section aria-label="ATR % 位置條" className="flex flex-col gap-2 text-xs">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h3 className="text-stone-500">ATR 占收盤價百分比（0-6%+）</h3>
          <span className="text-stone-500">
            <span className="text-[10px] text-stone-400">ATR</span>
            <span className="ml-1 font-mono tabular-nums text-stone-900">
              {d.atr.toFixed(2)}
            </span>
            <span className="mx-1 text-stone-400">·</span>
            <span className="text-[10px] text-stone-400">收盤</span>
            <span className="ml-1 font-mono tabular-nums text-stone-700">
              {d.close.toFixed(2)}
            </span>
          </span>
        </div>
        <PositionGauge
          value={pctDisplay}
          min={GAUGE_MIN}
          max={GAUGE_MAX}
          zones={ZONES}
          ariaLabel={`ATR ${d.atr_pct.toFixed(2)}%`}
          highlightCurrentZone
        />
      </section>

      <TodayPill todayTr={d.today_tr} todayVsAtr={d.today_vs_atr} />
      <StopHint atr={d.atr} close={d.close} />
      <Watchpoints atrPct={d.atr_pct} />
    </div>
  );
}

function Watchpoints({ atrPct }: { atrPct: number }): JSX.Element {
  const zone: 'calm' | 'normal_up' | 'elevated' =
    atrPct >= 4 ? 'elevated' : atrPct >= 2 ? 'normal_up' : 'calm';
  const items: Array<{ direction: 'up' | 'down'; threshold: number; nextLabel: string }> =
    zone === 'calm'
      ? [{ direction: 'up', threshold: 2, nextLabel: '🟡 波動正常偏上' }]
      : zone === 'normal_up'
        ? [
            { direction: 'down', threshold: 2, nextLabel: '🟢 波動平靜' },
            { direction: 'up', threshold: 4, nextLabel: '🔴 波動偏高 (部位減半)' },
          ]
        : [
            { direction: 'down', threshold: 4, nextLabel: '🟡 波動正常偏上' },
            { direction: 'down', threshold: 2, nextLabel: '🟢 波動平靜' },
          ];
  return (
    <section aria-label="ATR 看點" className="flex flex-col gap-2 text-xs">
      <h3 className="text-stone-500">
        <Explainable
          title="看點生成規則"
          explanation={
            <RuleTable
              preface="ATR% 兩條閾值決定部位大小框架："
              rows={[
                {
                  condition: '🟢 波動平靜 (ATR% < 2%)',
                  result: '只看「升至 2% → 波動正常偏上」',
                  current: zone === 'calm',
                },
                {
                  condition: '🟡 波動正常偏上 (2% ≤ ATR% < 4%)',
                  result: '雙向 (跌至 2% → 平靜 / 升至 4% → 偏高,部位減半)',
                  current: zone === 'normal_up',
                },
                {
                  condition: '🔴 波動偏高 (ATR% ≥ 4%)',
                  result: '兩條皆為「恢復條件」',
                  current: zone === 'elevated',
                },
              ]}
              note="2% / 4% 是業界波動分區慣例;個股 volatility 較高可能需要再上調。"
            />
          }
        >
          看點
        </Explainable>
        <span className="ml-1 text-stone-400">（觸發轉態勢的關鍵 ATR%）</span>
      </h3>
      <ul className="flex flex-col gap-1">
        {items.map((p) => (
          <li
            key={`${p.direction}-${p.threshold}`}
            className="flex flex-wrap items-center gap-2 rounded-md border border-stone-200 bg-stone-50 px-2 py-1"
          >
            <span className="text-stone-700">
              ATR% {p.direction === 'up' ? '升至' : '跌至'} {p.threshold.toFixed(0)}%
            </span>
            <span className="text-stone-400">→</span>
            <span className="text-stone-700">{p.nextLabel}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function TodayPill({
  todayTr,
  todayVsAtr,
}: {
  todayTr: number | null;
  todayVsAtr: number | null;
}): JSX.Element {
  const ratio = todayVsAtr ?? 0;
  const tone =
    ratio >= 1.5
      ? 'border-signal-red/40 bg-signal-red/10 text-signal-red'
      : ratio >= 1.0
        ? 'border-amber-400/40 bg-amber-50 text-amber-700'
        : 'border-stone-200 bg-stone-50 text-stone-700';
  const label =
    ratio >= 1.5
      ? '🔴 今日異常大震 (≥ 1.5 ATR)'
      : ratio >= 1.0
        ? '🟡 今日略大 (~1 ATR)'
        : '🟢 今日震幅正常 (< 1 ATR)';
  return (
    <section
      aria-label="今日震幅 vs ATR"
      className={`flex items-center gap-2 rounded-md border px-3 py-2 text-xs ${tone}`}
    >
      <Explainable
        title="今日震幅與 ATR 比較"
        explanation={
          <p className="leading-relaxed text-stone-700">
            今日 True Range / 14 期 ATR。&lt; 1 = 比平均日小,&gt; 1.5 = 比平均日大 50% 以上 —
            通常代表有未消化的訊息(財報、新聞、事件)。連續 2 ATR 的日不少於 1 個月會發生
            一次,所以這個訊號偶發性高、解讀要配合催化劑日曆。
          </p>
        }
      >
        <span className="font-medium">{label}</span>
      </Explainable>
      <span className="ml-auto text-stone-500">
        今日 TR {todayTr?.toFixed(2) ?? '—'} ·{' '}
        ratio {todayVsAtr?.toFixed(2) ?? '—'}
      </span>
    </section>
  );
}

function StopHint({ atr, close }: { atr: number; close: number }): JSX.Element {
  const stop = close - 2 * atr;
  const stopPct = ((close - stop) / close) * 100;
  return (
    <section
      aria-label="停損距離參考"
      className="flex flex-col gap-1 rounded-md border border-stone-200 bg-stone-50 px-3 py-2 text-xs"
    >
      <h3 className="text-stone-500">
        <Explainable
          title="為什麼用 ATR 算停損"
          explanation={
            <p className="leading-relaxed text-stone-700">
              較固定 % 停損更尊重股票本身波動 — 波動股自動拉寬,平靜股自動縮緊。
              連續 2 ATR 內的回測通常還屬於正常波動,不視為趨勢破壞。
            </p>
          }
        >
          停損距離參考（2 ATR）
        </Explainable>
      </h3>
      <p className="text-stone-700">
        若以 <span className="font-mono">close − 2 × ATR</span> 為停損 →{' '}
        <span className="font-mono text-stone-900">${stop.toFixed(2)}</span>{' '}
        <span className="text-stone-500">
          (距收盤 -{stopPct.toFixed(1)}%)
        </span>
      </p>
    </section>
  );
}
