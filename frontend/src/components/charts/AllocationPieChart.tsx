import { useMemo } from 'react';

export interface PieSlice {
  label: string;
  value: number;
  color?: string;
}

export interface AllocationPieChartProps {
  slices: readonly PieSlice[];
  size?: number;
}

// Palette — keeps the Tailwind slate/sky/teal vocabulary the rest of
// the UI uses. The donut cycles through this list when a slice doesn't
// specify an explicit colour.
const PALETTE: readonly string[] = [
  '#94a3b8', // slate-400
  '#38bdf8', // sky-400
  '#2dd4bf', // teal-400
  '#fbbf24', // amber-400
  '#fb7185', // rose-400
  '#a78bfa', // violet-400
  '#f472b6', // pink-400
  '#4ade80', // green-400
];

interface ArcDescriptor {
  label: string;
  value: number;
  percent: number;
  path: string;
  color: string;
}

function polarToCartesian(
  cx: number,
  cy: number,
  radius: number,
  angle: number,
): { x: number; y: number } {
  // `angle` is in radians, measured clockwise from the top (12 o'clock)
  // which is the convention most readers expect for a pie chart.
  return {
    x: cx + radius * Math.sin(angle),
    y: cy - radius * Math.cos(angle),
  };
}

function describeDonutSlice(
  cx: number,
  cy: number,
  outerRadius: number,
  innerRadius: number,
  startAngle: number,
  endAngle: number,
): string {
  const outerStart = polarToCartesian(cx, cy, outerRadius, endAngle);
  const outerEnd = polarToCartesian(cx, cy, outerRadius, startAngle);
  const innerStart = polarToCartesian(cx, cy, innerRadius, startAngle);
  const innerEnd = polarToCartesian(cx, cy, innerRadius, endAngle);
  const largeArc = endAngle - startAngle > Math.PI ? 1 : 0;
  return [
    `M ${outerStart.x} ${outerStart.y}`,
    `A ${outerRadius} ${outerRadius} 0 ${largeArc} 0 ${outerEnd.x} ${outerEnd.y}`,
    `L ${innerStart.x} ${innerStart.y}`,
    `A ${innerRadius} ${innerRadius} 0 ${largeArc} 1 ${innerEnd.x} ${innerEnd.y}`,
    'Z',
  ].join(' ');
}

function describeFullDonut(
  cx: number,
  cy: number,
  outerRadius: number,
  innerRadius: number,
): string {
  // A single slice covering a full 2π can't be drawn via arc commands;
  // stitch two halves instead.
  const topOuter = polarToCartesian(cx, cy, outerRadius, 0);
  const bottomOuter = polarToCartesian(cx, cy, outerRadius, Math.PI);
  const topInner = polarToCartesian(cx, cy, innerRadius, 0);
  const bottomInner = polarToCartesian(cx, cy, innerRadius, Math.PI);
  return [
    `M ${topOuter.x} ${topOuter.y}`,
    `A ${outerRadius} ${outerRadius} 0 1 0 ${bottomOuter.x} ${bottomOuter.y}`,
    `A ${outerRadius} ${outerRadius} 0 1 0 ${topOuter.x} ${topOuter.y}`,
    `M ${topInner.x} ${topInner.y}`,
    `A ${innerRadius} ${innerRadius} 0 1 1 ${bottomInner.x} ${bottomInner.y}`,
    `A ${innerRadius} ${innerRadius} 0 1 1 ${topInner.x} ${topInner.y}`,
    'Z',
  ].join(' ');
}

function formatPercent(pct: number): string {
  // 1dp absorbs the cumulative rounding drift without looking noisy.
  return `${pct.toFixed(1)}%`;
}

function formatValue(value: number): string {
  return value.toLocaleString('en-US', {
    maximumFractionDigits: 2,
  });
}

export function AllocationPieChart({
  slices,
  size = 200,
}: AllocationPieChartProps): JSX.Element {
  const total = useMemo(
    () => slices.reduce((sum, s) => sum + (s.value > 0 ? s.value : 0), 0),
    [slices],
  );

  const arcs = useMemo<ArcDescriptor[]>(() => {
    if (total <= 0) return [];
    const cx = size / 2;
    const cy = size / 2;
    const outerRadius = size / 2;
    const innerRadius = size / 2 - size * 0.18;

    const filtered = slices.filter((s) => s.value > 0);

    if (filtered.length === 1) {
      const only = filtered[0];
      if (!only) return [];
      return [
        {
          label: only.label,
          value: only.value,
          percent: 100,
          path: describeFullDonut(cx, cy, outerRadius, innerRadius),
          color: only.color ?? PALETTE[0] ?? '#94a3b8',
        },
      ];
    }

    let cursorAngle = 0;
    const result: ArcDescriptor[] = [];
    filtered.forEach((slice, idx) => {
      const fraction = slice.value / total;
      const startAngle = cursorAngle;
      const endAngle = cursorAngle + fraction * Math.PI * 2;
      cursorAngle = endAngle;
      result.push({
        label: slice.label,
        value: slice.value,
        percent: fraction * 100,
        path: describeDonutSlice(cx, cy, outerRadius, innerRadius, startAngle, endAngle),
        color: slice.color ?? PALETTE[idx % PALETTE.length] ?? '#94a3b8',
      });
    });
    return result;
  }, [slices, total, size]);

  const ariaLabel = useMemo(() => {
    if (arcs.length === 0) return '資產配置：無持倉';
    const parts = arcs.map((a) => `${a.label} ${formatPercent(a.percent)}`);
    return `資產配置：${parts.join('、')}`;
  }, [arcs]);

  if (arcs.length === 0) {
    return (
      <div
        role="status"
        data-testid="allocation-empty"
        className="flex h-48 w-full items-center justify-center rounded-md border border-dashed border-slate-800 bg-slate-900/40 text-sm text-slate-400"
      >
        尚未建立持倉
      </div>
    );
  }

  return (
    <div
      className="flex flex-col items-center gap-4 sm:flex-row sm:items-center sm:justify-start"
      data-testid="allocation-pie"
    >
      <svg
        role="img"
        aria-label={ariaLabel}
        viewBox={`0 0 ${size} ${size}`}
        width={size}
        height={size}
        className="shrink-0"
      >
        {arcs.map((arc) => (
          <path
            key={arc.label}
            d={arc.path}
            fill={arc.color}
            stroke="#0f172a"
            strokeWidth={1}
            fillRule="evenodd"
          />
        ))}
      </svg>
      <ul
        data-testid="allocation-legend"
        className="flex flex-wrap gap-x-4 gap-y-2 text-sm sm:flex-col sm:gap-y-1.5"
      >
        {arcs.map((arc) => (
          <li key={arc.label} className="flex items-center gap-2">
            <span
              aria-hidden="true"
              className="inline-block h-3 w-3 shrink-0 rounded-sm"
              style={{ backgroundColor: arc.color }}
            />
            <span className="font-mono text-slate-100">{arc.label}</span>
            <span className="text-slate-400">{formatPercent(arc.percent)}</span>
            <span className="text-xs text-slate-500">({formatValue(arc.value)})</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
