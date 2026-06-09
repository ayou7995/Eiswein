import { z } from 'zod';
import { Explainable, RuleTable } from './Explainable';
import { TrendPill, type TrendDirection } from './TrendPill';

// DXY detail emitted by `app/indicators/macro/dxy.py`. The classifier
// depends only on the boolean streak flags + the 5-day MA20 delta; we
// don't need any kind of position gauge because the regime is direction-
// only ("方向不明" sits between RED and GREEN, not on a value scale).
const dxyDetailSchema = z.object({
  ma20: z.number(),
  streak_rising: z.boolean(),
  streak_falling: z.boolean(),
  streak_days: z.number().int(),
  ma20_change_last_5d: z.number().nullable().optional(),
});

type DxyDetail = z.infer<typeof dxyDetailSchema>;
type DxySignal = 'strong' | 'weak' | 'mixed';

function classifySignal(d: DxyDetail): DxySignal {
  if (d.streak_rising) return 'strong';
  if (d.streak_falling) return 'weak';
  return 'mixed';
}

const SIGNAL_LABEL: Record<DxySignal, string> = {
  strong: '🔴 走強（科技股逆風）',
  weak: '🟢 走弱（科技股順風）',
  mixed: '🟡 方向不明',
};

const TREND_INTERPRETATIONS: Record<TrendDirection, string> = {
  rising: 'DXY 走強，科技股逆風',
  falling: 'DXY 走弱，科技股順風',
  flat: 'MA20 5 日無明確方向',
  unknown: '資料不足以計算',
};

function trendDirection(d: DxyDetail): TrendDirection {
  if (d.streak_rising) return 'rising';
  if (d.streak_falling) return 'falling';
  return 'flat';
}

export interface DxyHeadlineLabels {
  ruleTitle: string;
  ruleNote: string;
}

export function DxyHeadlineExplainable({
  shortLabel,
  detail,
  labels,
}: {
  shortLabel: string;
  detail: Record<string, unknown>;
  labels: DxyHeadlineLabels;
}): JSX.Element {
  const parsed = dxyDetailSchema.safeParse(detail);
  if (!parsed.success) return <span>{shortLabel}</span>;
  const d = parsed.data;
  const signal = classifySignal(d);
  return (
    <Explainable
      title={labels.ruleTitle}
      explanation={
        <RuleTable
          preface="美元指數 (DXY) 20MA 連續 5 日方向 — 與科技股反向關係："
          rows={[
            {
              condition: '5 連 MA20 上升',
              result: '🔴 DXY 走強（科技股逆風）',
              current: signal === 'strong',
            },
            {
              condition: '5 連 MA20 下降',
              result: '🟢 DXY 走弱（科技股順風）',
              current: signal === 'weak',
            },
            {
              condition: '其他（含混合方向）',
              result: '🟡 方向不明',
              current: signal === 'mixed',
            },
          ]}
          currentValueText={`你目前: MA20=${d.ma20.toFixed(2)}, 5 日變化 ${formatChange(d.ma20_change_last_5d)} → ${SIGNAL_LABEL[signal]}`}
          note={labels.ruleNote}
        />
      }
    >
      {shortLabel}
    </Explainable>
  );
}

export function DxyEnhancedDetail({
  detail,
}: {
  detail: Record<string, unknown>;
}): JSX.Element | null {
  const parsed = dxyDetailSchema.safeParse(detail);
  if (!parsed.success) return null;
  const d = parsed.data;
  return (
    <div className="flex flex-col gap-3 px-3 py-3 text-sm">
      <TrendPill
        direction={trendDirection(d)}
        magnitude={d.ma20_change_last_5d ?? null}
        windowLabel="20MA 5 日變化"
        interpretations={TREND_INTERPRETATIONS}
      />
      <Watchpoints detail={d} />
    </div>
  );
}

function Watchpoints({ detail }: { detail: DxyDetail }): JSX.Element {
  const zone: 'rising' | 'falling' | 'mixed' = detail.streak_rising
    ? 'rising'
    : detail.streak_falling
      ? 'falling'
      : 'mixed';
  const items: Array<{ trigger: string; nextLabel: string }> =
    zone === 'mixed'
      ? [
          { trigger: 'MA20 連 5 日上升', nextLabel: '🔴 走強確立 (科技股逆風)' },
          { trigger: 'MA20 連 5 日下降', nextLabel: '🟢 走弱確立 (科技股順風)' },
        ]
      : zone === 'rising'
        ? [{ trigger: 'MA20 streak 中斷 / 反向', nextLabel: '🟡 方向不明' }]
        : [{ trigger: 'MA20 streak 中斷 / 反向', nextLabel: '🟡 方向不明' }];
  return (
    <section aria-label="DXY 看點" className="flex flex-col gap-2 text-xs">
      <h3 className="text-stone-500">
        <Explainable
          title="看點生成規則"
          explanation={
            <RuleTable
              preface="DXY 趨勢看 20MA 連 5 日同方向 streak —"
              rows={[
                {
                  condition: '🟡 方向不明',
                  result: '雙向 (連 5 日↑ → 走強 / 連 5 日↓ → 走弱)',
                  current: zone === 'mixed',
                },
                {
                  condition: '🔴 走強 / 🟢 走弱',
                  result: '只看「streak 中斷 → 方向不明」',
                  current: zone === 'rising' || zone === 'falling',
                },
              ]}
              note="5 日是業界 streak 慣例;太短會被雜訊主導,太長會錯過轉折。"
            />
          }
        >
          看點
        </Explainable>
        <span className="ml-1 text-stone-400">（觸發轉態勢的關鍵 streak）</span>
      </h3>
      <ul className="flex flex-col gap-1">
        {items.map((p) => (
          <li
            key={p.trigger}
            className="flex flex-wrap items-center gap-2 rounded-md border border-stone-200 bg-stone-50 px-2 py-1"
          >
            <span className="text-stone-700">{p.trigger}</span>
            <span className="text-stone-400">→</span>
            <span className="text-stone-700">{p.nextLabel}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function formatChange(n: number | null | undefined): string {
  if (n === null || n === undefined) return '—';
  return `${n >= 0 ? '+' : ''}${n.toFixed(2)}`;
}
