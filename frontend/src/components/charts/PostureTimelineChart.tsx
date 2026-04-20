import { useMemo, useState } from 'react';
import type { PostureHistoryItem } from '../../api/history';

// We render the timeline as a coloured strip rather than a line/bar
// chart from lightweight-charts because posture is a categorical label,
// not a value. A vertical bar per trading day is both mobile-friendly
// and carries accurate information density on small screens.

export interface PostureTimelineChartProps {
  data: readonly PostureHistoryItem[];
}

const POSTURE_LABEL: Record<PostureHistoryItem['posture'], string> = {
  offensive: '進攻',
  normal: '正常',
  defensive: '防守',
};

const POSTURE_COLOR: Record<PostureHistoryItem['posture'], string> = {
  offensive: '#22c55e',
  normal: '#eab308',
  defensive: '#ef4444',
};

interface HoverInfo {
  index: number;
  x: number;
}

export function PostureTimelineChart({
  data,
}: PostureTimelineChartProps): JSX.Element {
  const [hover, setHover] = useState<HoverInfo | null>(null);

  const stats = useMemo(() => {
    const counts: Record<PostureHistoryItem['posture'], number> = {
      offensive: 0,
      normal: 0,
      defensive: 0,
    };
    data.forEach((item) => {
      counts[item.posture] += 1;
    });
    const total = data.length;
    const pct = (n: number): number =>
      total === 0 ? 0 : Math.round((n / total) * 1000) / 10;
    return {
      total,
      offensive: counts.offensive,
      normal: counts.normal,
      defensive: counts.defensive,
      offensivePct: pct(counts.offensive),
      normalPct: pct(counts.normal),
      defensivePct: pct(counts.defensive),
    };
  }, [data]);

  if (data.length === 0) {
    return (
      <div
        role="status"
        data-testid="posture-timeline-empty"
        className="flex h-32 w-full items-center justify-center rounded-md border border-dashed border-slate-800 bg-slate-900/40 text-sm text-slate-400"
      >
        無市場態勢歷史
      </div>
    );
  }

  const firstDate = data[0]?.date ?? '';
  const lastDate = data[data.length - 1]?.date ?? '';
  const hoveredItem = hover ? data[hover.index] : null;

  return (
    <div
      className="flex flex-col gap-2"
      data-testid="posture-timeline"
      onMouseLeave={() => setHover(null)}
    >
      <div className="relative h-16 overflow-hidden rounded-md border border-slate-800 bg-slate-950">
        <svg
          viewBox={`0 0 ${Math.max(data.length, 1)} 10`}
          preserveAspectRatio="none"
          className="h-full w-full"
          role="img"
          aria-label={`市場態勢時間軸，共 ${data.length} 天，由 ${firstDate} 至 ${lastDate}`}
          onMouseMove={(e) => {
            const target = e.currentTarget;
            const rect = target.getBoundingClientRect();
            const xRatio = (e.clientX - rect.left) / rect.width;
            const idx = Math.min(
              data.length - 1,
              Math.max(0, Math.floor(xRatio * data.length)),
            );
            setHover({ index: idx, x: e.clientX - rect.left });
          }}
        >
          {data.map((item, idx) => (
            <rect
              key={item.date}
              x={idx}
              y={0}
              width={1}
              height={10}
              fill={POSTURE_COLOR[item.posture]}
            >
              <title>
                {item.date} — {POSTURE_LABEL[item.posture]}
              </title>
            </rect>
          ))}
        </svg>
        {hoveredItem && (
          <div
            aria-hidden="true"
            className="pointer-events-none absolute top-1 rounded bg-slate-950/90 px-2 py-1 text-[10px] text-slate-100 shadow"
            style={{
              left: hover ? Math.min(hover.x + 8, 280) : 0,
            }}
          >
            {hoveredItem.date} · {POSTURE_LABEL[hoveredItem.posture]}
          </div>
        )}
      </div>
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 text-xs text-slate-400">
        <span>{firstDate}</span>
        <span>{lastDate}</span>
      </div>
      <dl className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
        <StatRow label="進攻" count={stats.offensive} pct={stats.offensivePct} color={POSTURE_COLOR.offensive} />
        <StatRow label="正常" count={stats.normal} pct={stats.normalPct} color={POSTURE_COLOR.normal} />
        <StatRow label="防守" count={stats.defensive} pct={stats.defensivePct} color={POSTURE_COLOR.defensive} />
      </dl>
    </div>
  );
}

interface StatRowProps {
  label: string;
  count: number;
  pct: number;
  color: string;
}

function StatRow({ label, count, pct, color }: StatRowProps): JSX.Element {
  return (
    <div className="flex items-center gap-1.5">
      <span
        aria-hidden="true"
        className="inline-block h-2.5 w-2.5 rounded-sm"
        style={{ backgroundColor: color }}
      />
      <dt className="text-slate-300">{label}</dt>
      <dd className="font-mono text-slate-400">
        {count} 日 ({pct}%)
      </dd>
    </div>
  );
}
