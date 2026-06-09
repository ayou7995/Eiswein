import { z } from 'zod';
import { Explainable, RuleTable } from './Explainable';
import { PositionGauge, type PositionGaugeZone } from './PositionGauge';

// Per-ticker TTM Squeeze detail emitted by ``app/indicators/timing/ttm_squeeze.py``.
const ttmDetailSchema = z.object({
  squeeze_on: z.boolean(),
  fired_up: z.boolean(),
  fired_down: z.boolean(),
  momentum: z.number(),
  momentum_rising: z.boolean(),
  bb_upper: z.number(),
  bb_lower: z.number(),
  kc_upper: z.number(),
  kc_lower: z.number(),
  length: z.number().optional().default(20),
});

// Momentum is reported as % of close (post-Phase-3 normalisation) so the
// gauge bands are now in price-percent units, cross-ticker comparable.
// ±2% per bar is a strong squeeze release; ±5% is rare event-driven (earnings).
const GAUGE_RANGE = 5;

const ZONES: ReadonlyArray<PositionGaugeZone> = [
  {
    upTo: -0.5,
    label: '向下',
    bg: 'bg-signal-red/30',
    text: 'text-signal-red',
  },
  {
    upTo: 0.5,
    label: '中性',
    bg: 'bg-stone-200',
    text: 'text-stone-700',
  },
  {
    upTo: GAUGE_RANGE,
    label: '向上',
    bg: 'bg-signal-green/30',
    text: 'text-signal-green',
  },
];

export interface TtmSqueezeHeadlineLabels {
  ruleTitle: string;
  ruleNote: string;
}

export function TtmSqueezeHeadlineExplainable({
  shortLabel,
  detail,
  labels,
}: {
  shortLabel: string;
  detail: Record<string, unknown>;
  labels: TtmSqueezeHeadlineLabels;
}): JSX.Element {
  const parsed = ttmDetailSchema.safeParse(detail);
  if (!parsed.success) return <span>{shortLabel}</span>;
  const d = parsed.data;
  return (
    <Explainable
      title={labels.ruleTitle}
      explanation={
        <RuleTable
          preface="TTM Squeeze (John Carter, 2007) 偵測「波動率被壓縮 → 即將爆發」的訊號。布林通道在 Keltner Channel 之內 = squeeze 醞釀中（多空力量平衡、隨時引爆）。當 BB 突破 KC 時叫做「點火」,方向由動能 oscillator（close − 區間中點，再做 20 期線性回歸斜率）決定。"
          rows={[
            {
              condition: 'BB 突破 KC 且動能正向',
              result: '🟢 向上點火 — 短期 5-vote 中投綠票',
              current: d.fired_up,
            },
            {
              condition: 'BB 突破 KC 且動能負向',
              result: '🔴 向下點火 — 短期 5-vote 中投紅票',
              current: d.fired_down,
            },
            {
              condition: 'BB 仍在 KC 之內 (squeeze ON)',
              result: '🟡 醞釀中 — 等待點火,先別動',
              current: d.squeeze_on && !d.fired_up && !d.fired_down,
            },
            {
              condition: '無壓縮、無近期點火',
              result: '🟡 中性 — 不投綠/紅票',
              current: !d.squeeze_on && !d.fired_up && !d.fired_down,
            },
          ]}
          currentValueText={`你目前: ${d.squeeze_on ? '壓縮中' : '已釋放'} · 動能 ${d.momentum >= 0 ? '+' : ''}${d.momentum.toFixed(2)}%${d.momentum_rising ? ' ↑' : ' ↓'}`}
          note={labels.ruleNote}
        />
      }
    >
      {shortLabel}
    </Explainable>
  );
}

export function TtmSqueezeEnhancedDetail({
  detail,
}: {
  detail: Record<string, unknown>;
}): JSX.Element | null {
  const parsed = ttmDetailSchema.safeParse(detail);
  if (!parsed.success) return null;
  const d = parsed.data;
  const momentumDisplay = Math.max(-GAUGE_RANGE, Math.min(GAUGE_RANGE, d.momentum));
  return (
    <div className="flex flex-col gap-3 px-3 py-3 text-sm">
      <section
        aria-label="TTM 動能尺標"
        className="flex flex-col gap-2 text-xs"
      >
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h3 className="text-stone-500">動能（% of close per bar, ±5%）</h3>
          <span className="text-stone-500">
            <span className="text-[10px] text-stone-400">動能</span>
            <span className="ml-1 font-mono tabular-nums text-stone-900">
              {d.momentum >= 0 ? '+' : ''}
              {d.momentum.toFixed(2)}%
            </span>
            <span className="ml-2 text-stone-400">
              {d.momentum_rising ? '↑ 加速中' : '↓ 減速中'}
            </span>
          </span>
        </div>
        <PositionGauge
          value={momentumDisplay}
          min={-GAUGE_RANGE}
          max={GAUGE_RANGE}
          zones={ZONES}
          ariaLabel={`TTM momentum ${d.momentum.toFixed(2)}`}
          highlightCurrentZone
        />
      </section>

      <SqueezeStatePill detail={d} />
      <BandsTable detail={d} />
      <Watchpoints detail={d} />
    </div>
  );
}

function Watchpoints({
  detail,
}: {
  detail: z.infer<typeof ttmDetailSchema>;
}): JSX.Element {
  const zone: 'fired_up' | 'fired_down' | 'loaded' | 'idle' = detail.fired_up
    ? 'fired_up'
    : detail.fired_down
      ? 'fired_down'
      : detail.squeeze_on
        ? 'loaded'
        : 'idle';
  const items: Array<{ trigger: string; nextLabel: string }> =
    zone === 'idle'
      ? [{ trigger: 'BB 寬 < KC 寬 持續 6 根日', nextLabel: '🟡 squeeze 醞釀中' }]
      : zone === 'loaded'
        ? [
            { trigger: '動能轉正 + BB 突破 KC', nextLabel: '🟢 向上點火 (順向追多)' },
            { trigger: '動能轉負 + BB 突破 KC', nextLabel: '🔴 向下點火 (順向追空)' },
          ]
        : zone === 'fired_up'
          ? [{ trigger: '動能轉負 / BB 再次縮回 KC', nextLabel: '🟡 再壓縮 (等下次點火)' }]
          : [{ trigger: '動能轉正 / BB 再次縮回 KC', nextLabel: '🟡 再壓縮 (等下次點火)' }];
  return (
    <section aria-label="Squeeze 看點" className="flex flex-col gap-2 text-xs">
      <h3 className="text-stone-500">
        <Explainable
          title="看點生成規則"
          explanation={
            <RuleTable
              preface="TTM Squeeze 是狀態機:壓縮 → 點火 → 再壓縮 循環。"
              rows={[
                {
                  condition: '⚪ 無壓縮 / 待醞釀',
                  result: '只看「BB 寬 < KC 寬 持續 6 根日 → 醞釀」',
                  current: zone === 'idle',
                },
                {
                  condition: '🟡 squeeze 醞釀中',
                  result: '雙向 (動能轉正 → 向上點火 / 動能轉負 → 向下點火)',
                  current: zone === 'loaded',
                },
                {
                  condition: '🟢/🔴 點火中',
                  result: '只看「動能反向 / 再壓縮」',
                  current: zone === 'fired_up' || zone === 'fired_down',
                },
              ]}
              note="點火後的延續通常 6-10 根日;再壓縮代表能量重新累積,等下次點火。"
            />
          }
        >
          看點
        </Explainable>
        <span className="ml-1 text-stone-400">（觸發轉態勢的關鍵狀態）</span>
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

function SqueezeStatePill({
  detail,
}: {
  detail: z.infer<typeof ttmDetailSchema>;
}): JSX.Element {
  let tone: string;
  let label: string;
  if (detail.fired_up) {
    tone = 'border-signal-green/40 bg-signal-green/10 text-signal-green';
    label = '🟢 向上點火 — 5-vote 投綠票';
  } else if (detail.fired_down) {
    tone = 'border-signal-red/40 bg-signal-red/10 text-signal-red';
    label = '🔴 向下點火 — 5-vote 投紅票';
  } else if (detail.squeeze_on) {
    tone = 'border-amber-400/40 bg-amber-50 text-amber-700';
    label = '🟡 squeeze 醞釀中 — 等點火';
  } else {
    tone = 'border-stone-200 bg-stone-50 text-stone-700';
    label = '⚪ 無壓縮 — 中性, 不投票';
  }
  return (
    <section
      aria-label="Squeeze 狀態"
      className={`flex items-center gap-2 rounded-md border px-3 py-2 text-xs ${tone}`}
    >
      <span className="font-medium">{label}</span>
      <span className="ml-auto text-stone-500">
        BB [{detail.bb_lower.toFixed(2)}, {detail.bb_upper.toFixed(2)}] · KC [
        {detail.kc_lower.toFixed(2)}, {detail.kc_upper.toFixed(2)}]
      </span>
    </section>
  );
}

function BandsTable({
  detail,
}: {
  detail: z.infer<typeof ttmDetailSchema>;
}): JSX.Element {
  const bbWidth = detail.bb_upper - detail.bb_lower;
  const kcWidth = detail.kc_upper - detail.kc_lower;
  const compressionPct = (bbWidth / kcWidth) * 100;
  return (
    <section
      aria-label="壓縮率"
      className="flex flex-col gap-1 rounded-md border border-stone-200 bg-stone-50 px-3 py-2 text-xs"
    >
      <h3 className="text-stone-500">壓縮率（BB 寬 / KC 寬）</h3>
      <p className="text-stone-700">
        <span className="font-mono text-stone-900">{compressionPct.toFixed(0)}%</span>{' '}
        — 100% 以下代表布林通道完全縮在 Keltner 之內 (squeeze ON)。
        通常需要連續 6+ 根日 squeeze 才會產生有意義的點火。
      </p>
    </section>
  );
}
