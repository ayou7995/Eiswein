import { useMemo, useState } from 'react';

export type CategoricalClassification = 'accum' | 'distrib' | 'neutral';

export interface CategoricalBarsRow {
  readonly date: string;
  readonly classification: CategoricalClassification;
}

export interface CategoricalColors {
  readonly accum: string;
  readonly distrib: string;
  readonly neutral: string;
}

export interface CategoricalLabels {
  readonly accum: string;
  readonly distrib: string;
  readonly neutral: string;
}

export interface IndicatorCategoricalBarsProps {
  readonly series: ReadonlyArray<CategoricalBarsRow>;
  readonly colors: CategoricalColors;
  readonly legendLabels: CategoricalLabels;
  readonly height?: number;
  readonly ariaLabel: string;
}

const VIEWBOX_WIDTH = 1000;
const GAP_RATIO = 0.18;

interface HoverState {
  readonly index: number;
  readonly x: number;
  readonly y: number;
}

export function IndicatorCategoricalBars({
  series,
  colors,
  legendLabels,
  height = 32,
  ariaLabel,
}: IndicatorCategoricalBarsProps): JSX.Element {
  const [hover, setHover] = useState<HoverState | null>(null);

  const barLayout = useMemo(() => {
    if (series.length === 0) {
      return { width: 0, gap: 0 };
    }
    // Each bar occupies an equal slice; a small gap keeps adjacent bars
    // visually distinct on dense screens.
    const slot = VIEWBOX_WIDTH / series.length;
    const width = slot * (1 - GAP_RATIO);
    const gap = slot * GAP_RATIO;
    return { width, gap };
  }, [series.length]);

  const colorFor = (classification: CategoricalClassification): string => {
    if (classification === 'accum') return colors.accum;
    if (classification === 'distrib') return colors.distrib;
    return colors.neutral;
  };

  const labelFor = (classification: CategoricalClassification): string => {
    if (classification === 'accum') return legendLabels.accum;
    if (classification === 'distrib') return legendLabels.distrib;
    return legendLabels.neutral;
  };

  const hoveredRow = hover !== null ? series[hover.index] : null;

  return (
    <div className="flex flex-col gap-2">
      <ul className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-slate-300">
        <LegendSwatch color={colors.accum} label={legendLabels.accum} />
        <LegendSwatch color={colors.distrib} label={legendLabels.distrib} />
        <LegendSwatch color={colors.neutral} label={legendLabels.neutral} />
      </ul>
      <div className="relative w-full">
        {series.length === 0 ? (
          <div
            data-testid="indicator-categorical-bars-empty"
            role="img"
            aria-label={ariaLabel}
            className="flex w-full items-center justify-center rounded-md border border-slate-800 bg-slate-950 text-xs text-slate-500"
            style={{ height }}
          >
            無資料
          </div>
        ) : (
          <svg
            data-testid="indicator-categorical-bars"
            role="img"
            aria-label={ariaLabel}
            viewBox={`0 0 ${VIEWBOX_WIDTH} 100`}
            preserveAspectRatio="none"
            className="w-full rounded-md border border-slate-800 bg-slate-950"
            style={{ height }}
            onMouseLeave={() => setHover(null)}
          >
            {series.map((row, index) => {
              const slot = VIEWBOX_WIDTH / series.length;
              const x = index * slot + barLayout.gap / 2;
              return (
                <rect
                  key={`${row.date}-${index}`}
                  data-testid={`bar-${row.classification}`}
                  x={x}
                  y={0}
                  width={Math.max(barLayout.width, 0)}
                  height={100}
                  fill={colorFor(row.classification)}
                  onMouseEnter={(event) => {
                    const target = event.currentTarget;
                    const svg = target.ownerSVGElement;
                    if (!svg) return;
                    const rect = svg.getBoundingClientRect();
                    setHover({
                      index,
                      x: event.clientX - rect.left,
                      y: event.clientY - rect.top,
                    });
                  }}
                />
              );
            })}
          </svg>
        )}
        {hoveredRow && hover && (
          <div
            role="tooltip"
            data-testid="indicator-categorical-tooltip"
            className="pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-full rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-100 shadow-lg"
            style={{ left: hover.x, top: hover.y - 6 }}
          >
            <div className="font-mono">{hoveredRow.date}</div>
            <div className="text-slate-300">{labelFor(hoveredRow.classification)}</div>
          </div>
        )}
      </div>
    </div>
  );
}

interface LegendSwatchProps {
  color: string;
  label: string;
}

function LegendSwatch({ color, label }: LegendSwatchProps): JSX.Element {
  return (
    <li className="flex items-center gap-1.5">
      <span
        aria-hidden="true"
        className="inline-block h-3 w-3 rounded-sm"
        style={{ backgroundColor: color }}
      />
      <span>{label}</span>
    </li>
  );
}
