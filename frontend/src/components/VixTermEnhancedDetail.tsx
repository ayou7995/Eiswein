import { z } from 'zod';
import { Explainable, RuleTable } from './Explainable';
import { PositionGauge, type PositionGaugeZone } from './PositionGauge';

const vixTermDetailSchema = z.object({
  vix: z.number(),
  vix3m: z.number(),
  ratio: z.number(),
  contango_threshold: z.number().optional().default(0.95),
  inversion_threshold: z.number().optional().default(1.0),
});

const ZONES: ReadonlyArray<PositionGaugeZone> = [
  {
    upTo: 0.95,
    label: '深度 contango',
    bg: 'bg-signal-green/30',
    text: 'text-signal-green',
  },
  {
    upTo: 1.0,
    label: '平坦',
    bg: 'bg-amber-400/20',
    text: 'text-amber-700',
  },
  {
    upTo: 1.3,
    label: '倒掛',
    bg: 'bg-signal-red/30',
    text: 'text-signal-red',
  },
];

export interface VixTermHeadlineLabels {
  ruleTitle: string;
  ruleNote: string;
}

export function VixTermHeadlineExplainable({
  shortLabel,
  detail,
  labels,
}: {
  shortLabel: string;
  detail: Record<string, unknown>;
  labels: VixTermHeadlineLabels;
}): JSX.Element {
  const parsed = vixTermDetailSchema.safeParse(detail);
  if (!parsed.success) return <span>{shortLabel}</span>;
  const d = parsed.data;
  return (
    <Explainable
      title={labels.ruleTitle}
      explanation={
        <RuleTable
          preface="VIX 期限結構比較「現在的恐慌」與「未來 3 個月預期的恐慌」。Contango (比 < 1) = 短期波動率比 3 個月遠期便宜 = 市場平靜的標誌。倒掛 (比 ≥ 1) = 短期恐慌已超過 3 個月遠期 = 立即性壓力,通常在重大事件(銀行倒閉、地緣政治升溫)發生。比 VIX 絕對值更早反應市場結構性轉變。"
          rows={[
            {
              condition: `比 < ${d.contango_threshold} (深度 contango)`,
              result: '🟢 平靜 — 短期 posture 投綠',
              current: d.ratio < d.contango_threshold,
            },
            {
              condition: `${d.contango_threshold} ≤ 比 < ${d.inversion_threshold} (平坦)`,
              result: '🟡 接近平坦 — 觀察轉折',
              current:
                d.ratio >= d.contango_threshold &&
                d.ratio < d.inversion_threshold,
            },
            {
              condition: `比 ≥ ${d.inversion_threshold} (倒掛)`,
              result: '🔴 倒掛 — 短期 posture 投紅 (防守)',
              current: d.ratio >= d.inversion_threshold,
            },
          ]}
          currentValueText={`你目前: VIX ${d.vix.toFixed(2)} / VIX3M ${d.vix3m.toFixed(2)} = 比 ${d.ratio.toFixed(3)}`}
          note={labels.ruleNote}
        />
      }
    >
      {shortLabel}
    </Explainable>
  );
}

export function VixTermEnhancedDetail({
  detail,
}: {
  detail: Record<string, unknown>;
}): JSX.Element | null {
  const parsed = vixTermDetailSchema.safeParse(detail);
  if (!parsed.success) return null;
  const d = parsed.data;
  const ratioDisplay = Math.min(1.3, Math.max(0.5, d.ratio));
  return (
    <div className="flex flex-col gap-3 px-3 py-3 text-sm">
      <section
        aria-label="VIX 期限結構尺標"
        className="flex flex-col gap-2 text-xs"
      >
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h3 className="text-stone-500">VIX / VIX3M 比 (0.5 - 1.3 顯示範圍)</h3>
          <span className="text-stone-500">
            <span className="text-[10px] text-stone-400">VIX</span>
            <span className="ml-1 font-mono tabular-nums text-stone-900">
              {d.vix.toFixed(2)}
            </span>
            <span className="mx-1 text-stone-400">/</span>
            <span className="text-[10px] text-stone-400">VIX3M</span>
            <span className="ml-1 font-mono tabular-nums text-stone-700">
              {d.vix3m.toFixed(2)}
            </span>
          </span>
        </div>
        <PositionGauge
          value={ratioDisplay}
          min={0.5}
          max={1.3}
          zones={ZONES}
          ariaLabel={`VIX/VIX3M ratio ${d.ratio.toFixed(2)}`}
          highlightCurrentZone
        />
      </section>
      <InterpretPanel d={d} />
    </div>
  );
}

function InterpretPanel({
  d,
}: {
  d: z.infer<typeof vixTermDetailSchema>;
}): JSX.Element {
  const inverted = d.ratio >= 1.0;
  const tone = inverted
    ? 'border-signal-red/40 bg-signal-red/10 text-signal-red'
    : d.ratio >= 0.95
      ? 'border-amber-400/40 bg-amber-50 text-amber-700'
      : 'border-signal-green/40 bg-signal-green/10 text-signal-green';
  const label = inverted
    ? '🔴 倒掛 — 立即性壓力,部位先收'
    : d.ratio >= 0.95
      ? '🟡 平坦 — 觀察轉折'
      : '🟢 contango — 市場結構性平靜';
  return (
    <section
      aria-label="期限結構判讀"
      className={`flex items-center gap-2 rounded-md border px-3 py-2 text-xs ${tone}`}
    >
      <Explainable
        title="VIX vs VIX3M 怎麼讀"
        explanation={
          <p className="leading-relaxed text-stone-700">
            VIX 是 30 天隱含波動率,VIX3M 是 3 個月。正常狀態下市場給遠月一個 vol
            risk premium,所以 VIX3M 通常比 VIX 高 (比 &lt; 1)。當比 ≥ 1 時 =
            市場「現在」的恐慌已超過「3 個月後」的預期 — 通常是黑天鵝事件,
            機構大量買 1 個月 put 推升 VIX 所致。
          </p>
        }
      >
        <span className="font-medium">{label}</span>
      </Explainable>
    </section>
  );
}
