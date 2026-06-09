import { z } from 'zod';
import { Explainable, RuleTable } from './Explainable';

const choDetailSchema = z.object({
  cho: z.number(),
  prior: z.number(),
  slope_5d: z.number().nullable().optional(),
  flat_threshold: z.number(),
  volume_scale: z.number(),
  fast: z.number().optional().default(3),
  slow: z.number().optional().default(10),
});

// CHO is volume-weighted (cumsum × EMA differential), so raw values for
// actively-traded tickers naturally sit in the millions. Showing
// "-11,849,513" forces the operator to count zeroes; "-11.85M" is the
// universally-recognised compact form.
function formatCho(value: number): string {
  const abs = Math.abs(value);
  const sign = value >= 0 ? '+' : '−';
  const v = abs;
  if (v >= 1e9) return `${sign}${(v / 1e9).toFixed(2)}B`;
  if (v >= 1e6) return `${sign}${(v / 1e6).toFixed(2)}M`;
  if (v >= 1e3) return `${sign}${(v / 1e3).toFixed(2)}k`;
  return `${sign}${v.toFixed(2)}`;
}

export interface ChoHeadlineLabels {
  ruleTitle: string;
  ruleNote: string;
}

export function ChoHeadlineExplainable({
  shortLabel,
  detail,
  labels,
}: {
  shortLabel: string;
  detail: Record<string, unknown>;
  labels: ChoHeadlineLabels;
}): JSX.Element {
  const parsed = choDetailSchema.safeParse(detail);
  if (!parsed.success) return <span>{shortLabel}</span>;
  const d = parsed.data;
  const rising = d.cho > d.prior;
  return (
    <Explainable
      title={labels.ruleTitle}
      explanation={
        <RuleTable
          preface="Chaikin Oscillator (Marc Chaikin) 衡量「大戶吃貨/出貨的加速度」。底層是 A/D Line (累積分配線) — 每根 K 線的 close 落在 H-L 區間哪個位置,乘上量。CHO = EMA(AD, 3) − EMA(AD, 10),類似 MACD 但作用在資金流上。正值且加速 = 機構在加碼吃貨;負值且加速 = 機構在倒貨。對應 Sherry 的「綠燈群聚」概念。"
          rows={[
            {
              condition: 'CHO > 0 且高於前一日',
              result: '🟢 買盤加速 — 中期 5-vote 投綠票',
              current: d.cho > 0 && rising,
            },
            {
              condition: 'CHO < 0 且低於前一日',
              result: '🔴 賣盤加速 — 中期 5-vote 投紅票',
              current: d.cho < 0 && !rising,
            },
            {
              condition: `|CHO| < ${d.flat_threshold.toFixed(1)} (接近零線)`,
              result: '🟡 中性 — 大戶觀望',
              current: Math.abs(d.cho) < d.flat_threshold,
            },
            {
              condition: '同號但減速 (吃貨/倒貨力道在退)',
              result: '🟡 動能減弱 — 不投綠/紅票',
              current:
                Math.abs(d.cho) >= d.flat_threshold &&
                ((d.cho > 0 && !rising) || (d.cho < 0 && rising)),
            },
          ]}
          currentValueText={`你目前: CHO ${formatCho(d.cho)} (前日 ${formatCho(d.prior)}) · 差距 ${formatCho(d.cho - d.prior)}`}
          note={labels.ruleNote}
        />
      }
    >
      {shortLabel}
    </Explainable>
  );
}

export function ChoEnhancedDetail({
  detail,
}: {
  detail: Record<string, unknown>;
}): JSX.Element | null {
  const parsed = choDetailSchema.safeParse(detail);
  if (!parsed.success) return null;
  const d = parsed.data;
  const rising = d.cho > d.prior;
  const accumulating = d.cho > 0 && rising;
  const distributing = d.cho < 0 && !rising;
  return (
    <div className="flex flex-col gap-3 px-3 py-3 text-sm">
      <PhasePill
        accumulating={accumulating}
        distributing={distributing}
        nearZero={Math.abs(d.cho) < d.flat_threshold}
        cho={d.cho}
        rising={rising}
      />
      <Watchpoints detail={d} />
    </div>
  );
}

function Watchpoints({
  detail,
}: {
  detail: z.infer<typeof choDetailSchema>;
}): JSX.Element {
  const zone: 'positive' | 'near_zero' | 'negative' =
    Math.abs(detail.cho) < detail.flat_threshold
      ? 'near_zero'
      : detail.cho > 0
        ? 'positive'
        : 'negative';
  const items: Array<{ direction: 'up' | 'down'; threshold: string; nextLabel: string }> =
    zone === 'near_zero'
      ? [
          {
            direction: 'up',
            threshold: `+${formatCho(detail.flat_threshold)}`,
            nextLabel: '🟢/🟡 買盤確立',
          },
          {
            direction: 'down',
            threshold: `−${formatCho(detail.flat_threshold)}`,
            nextLabel: '🔴/🟡 賣盤確立',
          },
        ]
      : zone === 'positive'
        ? [
            {
              direction: 'down',
              threshold: '0',
              nextLabel: '🔴 賣盤確立 (零線跌破)',
            },
          ]
        : [
            {
              direction: 'up',
              threshold: '0',
              nextLabel: '🟢 買盤確立 (零線突破)',
            },
          ];
  return (
    <section aria-label="CHO 看點" className="flex flex-col gap-2 text-xs">
      <h3 className="text-stone-500">
        <Explainable
          title="看點生成規則"
          explanation={
            <RuleTable
              preface="CHO 零線是買/賣盤分界。Flat 區間(±flat_threshold)是「大戶觀望」中性區："
              rows={[
                {
                  condition: '⚪ 接近零線',
                  result: '雙向 (升至 +flat → 買盤 / 跌至 -flat → 賣盤)',
                  current: zone === 'near_zero',
                },
                {
                  condition: '🟢 CHO > 0',
                  result: '只看「跌破 0 → 賣盤確立」',
                  current: zone === 'positive',
                },
                {
                  condition: '🔴 CHO < 0',
                  result: '只看「突破 0 → 買盤確立」',
                  current: zone === 'negative',
                },
              ]}
              note="flat_threshold 隨成交量規模自動調整,跨市值股票仍可比較。"
            />
          }
        >
          看點
        </Explainable>
        <span className="ml-1 text-stone-400">（觸發轉態勢的關鍵 CHO 值）</span>
      </h3>
      <ul className="flex flex-col gap-1">
        {items.map((p) => (
          <li
            key={`${p.direction}-${p.threshold}`}
            className="flex flex-wrap items-center gap-2 rounded-md border border-stone-200 bg-stone-50 px-2 py-1"
          >
            <span className="text-stone-700">
              CHO {p.direction === 'up' ? '突破' : '跌破'} {p.threshold}
            </span>
            <span className="text-stone-400">→</span>
            <span className="text-stone-700">{p.nextLabel}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function PhasePill({
  accumulating,
  distributing,
  nearZero,
  cho,
  rising,
}: {
  accumulating: boolean;
  distributing: boolean;
  nearZero: boolean;
  cho: number;
  rising: boolean;
}): JSX.Element {
  let tone: string;
  let label: string;
  if (accumulating) {
    tone = 'border-signal-green/40 bg-signal-green/10 text-signal-green';
    label = '🟢 機構吃貨加速 (Sherry 綠燈)';
  } else if (distributing) {
    tone = 'border-signal-red/40 bg-signal-red/10 text-signal-red';
    label = '🔴 機構倒貨加速 (Sherry 紅燈)';
  } else if (nearZero) {
    tone = 'border-stone-200 bg-stone-50 text-stone-700';
    label = '⚪ 接近零線 — 大戶觀望';
  } else {
    tone = 'border-amber-400/40 bg-amber-50 text-amber-700';
    label = `🟡 ${cho > 0 ? '買盤' : '賣盤'}${rising ? '加速' : '減速'} — 訊號不夠強`;
  }
  return (
    <section
      aria-label="累積/分配階段"
      className={`flex items-center gap-2 rounded-md border px-3 py-2 text-xs ${tone}`}
    >
      <Explainable
        title="累積 vs 分配的解讀"
        explanation={
          <p className="leading-relaxed text-stone-700">
            CHO 正值 = 過去 10 天的累積買盤強過分配賣盤;負值反之。
            「加速」= 今日 CHO 比昨天更正/更負,代表力道在擴大。
            Sherry 系統的「綠燈群聚」就是這個概念 — 連續多日的機構吃貨。
          </p>
        }
      >
        <span className="font-medium">{label}</span>
      </Explainable>
    </section>
  );
}

