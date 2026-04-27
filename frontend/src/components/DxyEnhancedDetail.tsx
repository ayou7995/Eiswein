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
    </div>
  );
}

function formatChange(n: number | null | undefined): string {
  if (n === null || n === undefined) return '—';
  return `${n >= 0 ? '+' : ''}${n.toFixed(2)}`;
}
