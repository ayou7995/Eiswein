import { z } from 'zod';
import { Explainable, RuleTable } from './Explainable';

const adLineDetailSchema = z.object({
  advances: z.number(),
  declines: z.number(),
  net: z.number(),
  ad_line: z.number(),
  ad_slope_20d: z.number(),
  spx_slope_20d: z.number(),
  divergence: z.boolean(),
  lookback: z.number().optional().default(20),
});

export interface AdLineHeadlineLabels {
  ruleTitle: string;
  ruleNote: string;
}

export function AdLineHeadlineExplainable({
  shortLabel,
  detail,
  labels,
}: {
  shortLabel: string;
  detail: Record<string, unknown>;
  labels: AdLineHeadlineLabels;
}): JSX.Element {
  const parsed = adLineDetailSchema.safeParse(detail);
  if (!parsed.success) return <span>{shortLabel}</span>;
  const d = parsed.data;
  return (
    <Explainable
      title={labels.ruleTitle}
      explanation={
        <RuleTable
          preface="A/D Line 是「觀察名單裡多少股票同步上漲」的累積計數。每天 (上漲股數 − 下跌股數) 加總,觀察方向。標準用法:當 SPX 創新高但 A/D Line 沒有 → 「窄漲」,只有少數大股撐住指數,通常是回檔前兆。當 SPX + A/D Line 同步上升 → 廣度健康,大部分股票參與行情。"
          rows={[
            {
              condition: 'AD Line 上升 + SPX 上升 (廣度健康)',
              result: '🟢 大盤上漲且大部分名單參與',
              current: d.ad_slope_20d > 0 && d.spx_slope_20d > 0,
            },
            {
              condition: 'SPX 上升 + AD Line 下降 (負背離)',
              result: '🔴 窄漲警示 — 大盤上但廣度弱',
              current: d.ad_slope_20d <= 0 && d.spx_slope_20d > 0,
            },
            {
              condition: '其他 (大盤下跌 / 盤整)',
              result: '🟡 中性 — 不投綠票',
              current: !(d.ad_slope_20d > 0 && d.spx_slope_20d > 0) && d.spx_slope_20d <= 0,
            },
          ]}
          currentValueText={`你目前: 今日上漲 ${d.advances}/下跌 ${d.declines} (淨 ${d.net >= 0 ? '+' : ''}${d.net}) · AD Line 20日斜率 ${d.ad_slope_20d.toFixed(2)}, SPX 20日斜率 ${d.spx_slope_20d.toFixed(4)}`}
          note={labels.ruleNote}
        />
      }
    >
      {shortLabel}
    </Explainable>
  );
}

export function AdLineEnhancedDetail({
  detail,
}: {
  detail: Record<string, unknown>;
}): JSX.Element | null {
  const parsed = adLineDetailSchema.safeParse(detail);
  if (!parsed.success) return null;
  const d = parsed.data;
  return (
    <div className="flex flex-col gap-3 px-3 py-3 text-sm">
      <TodayBreadth d={d} />
      <DivergencePanel d={d} />
    </div>
  );
}

function TodayBreadth({
  d,
}: {
  d: z.infer<typeof adLineDetailSchema>;
}): JSX.Element {
  return (
    <section
      aria-label="今日觀察名單廣度"
      className="flex flex-col gap-1 rounded-md border border-stone-200 bg-stone-50 px-3 py-2 text-xs"
    >
      <h3 className="text-stone-500">今日觀察名單廣度</h3>
      <p className="text-stone-700">
        上漲{' '}
        <span className="font-mono text-signal-green">{d.advances}</span> /
        下跌{' '}
        <span className="font-mono text-signal-red">{d.declines}</span> · 淨{' '}
        <span className="font-mono text-stone-900">
          {d.net >= 0 ? '+' : ''}
          {d.net}
        </span>
        ,累積 AD Line ={' '}
        <span className="font-mono text-stone-900">{d.ad_line.toFixed(0)}</span>
      </p>
      <p className="text-stone-500">
        計算範圍是「所有使用者 watchlist 的並集」,所以是個人化的、Eiswein 專屬的廣度信號。
      </p>
    </section>
  );
}

function DivergencePanel({
  d,
}: {
  d: z.infer<typeof adLineDetailSchema>;
}): JSX.Element {
  let tone: string;
  let label: string;
  if (d.divergence) {
    tone = 'border-signal-red/40 bg-signal-red/10 text-signal-red';
    label = '🔴 負背離 — SPX 上升但觀察名單廣度下降';
  } else if (d.ad_slope_20d > 0 && d.spx_slope_20d > 0) {
    tone = 'border-signal-green/40 bg-signal-green/10 text-signal-green';
    label = '🟢 同步上升 — 大盤帶動觀察名單';
  } else if (d.ad_slope_20d < 0 && d.spx_slope_20d < 0) {
    tone = 'border-amber-400/40 bg-amber-50 text-amber-700';
    label = '🟡 同步下降 — 整體偏弱';
  } else {
    tone = 'border-stone-200 bg-stone-50 text-stone-700';
    label = '⚪ 盤整或混合';
  }
  return (
    <section
      aria-label="廣度 vs 大盤背離"
      className={`flex items-center gap-2 rounded-md border px-3 py-2 text-xs ${tone}`}
    >
      <Explainable
        title="廣度與大盤背離怎麼讀"
        explanation={
          <p className="leading-relaxed text-stone-700">
            O'Neil 系統用「廣度 vs 指數」的背離當作多頭末段警示。當 SPX 還在創新高但
            advance-decline 廣度開始走弱,代表只有少數大股 (Mag 7) 在撐,大部分中小型股
            已經先回檔了。歷史上多次大型回檔都先見到負背離。
          </p>
        }
      >
        <span className="font-medium">{label}</span>
      </Explainable>
      <span className="ml-auto text-stone-500">
        20 日斜率 AD={d.ad_slope_20d.toFixed(2)} · SPX={d.spx_slope_20d.toFixed(4)}
      </span>
    </section>
  );
}
