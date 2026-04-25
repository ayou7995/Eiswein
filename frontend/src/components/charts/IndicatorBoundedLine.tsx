import { useEffect, useRef, useState } from 'react';
import {
  createChart,
  ColorType,
  LineStyle,
  type IChartApi,
  type ISeriesApi,
  type LineData,
  type UTCTimestamp,
} from 'lightweight-charts';

export interface BoundedLineSeriesRow {
  readonly date: string;
  readonly [key: string]: number | string;
}

export interface BoundedLineDefinition {
  readonly key: string;
  readonly label: string;
  readonly color: string;
}

export interface BoundedLineThreshold {
  readonly value: number;
  readonly label: string;
  readonly color: string;
  readonly fillBetween?: 'above' | 'below';
}

export interface IndicatorBoundedLineProps {
  readonly series: ReadonlyArray<BoundedLineSeriesRow>;
  readonly lines: ReadonlyArray<BoundedLineDefinition>;
  readonly thresholds: ReadonlyArray<BoundedLineThreshold>;
  readonly yAxisMin?: number;
  readonly yAxisMax?: number;
  readonly height?: number;
  readonly ariaLabel: string;
}

function toUtcTimestamp(dateString: string): UTCTimestamp {
  const seconds = Math.floor(
    Date.UTC(
      Number.parseInt(dateString.slice(0, 4), 10),
      Number.parseInt(dateString.slice(5, 7), 10) - 1,
      Number.parseInt(dateString.slice(8, 10), 10),
    ) / 1000,
  );
  return seconds as UTCTimestamp;
}

function readNumber(row: BoundedLineSeriesRow, key: string): number | null {
  const raw = row[key];
  return typeof raw === 'number' && Number.isFinite(raw) ? raw : null;
}

function toLineData(
  series: ReadonlyArray<BoundedLineSeriesRow>,
  key: string,
): LineData[] {
  const out: LineData[] = [];
  for (const row of series) {
    const value = readNumber(row, key);
    if (value === null) continue;
    out.push({ time: toUtcTimestamp(row.date), value });
  }
  return out;
}

function applyOpacity(hexColor: string, opacity: number): string {
  const clamped = Math.min(1, Math.max(0, opacity));
  const alpha = Math.round(clamped * 255)
    .toString(16)
    .padStart(2, '0');
  if (/^#[0-9a-fA-F]{6}$/.test(hexColor)) return `${hexColor}${alpha}`;
  return hexColor;
}

export function IndicatorBoundedLine({
  series,
  lines,
  thresholds,
  yAxisMin,
  yAxisMax,
  height = 200,
  ariaLabel,
}: IndicatorBoundedLineProps): JSX.Element {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const lineSeriesRef = useRef<Map<string, ISeriesApi<'Line'>>>(new Map());
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return undefined;
    const lineMap = lineSeriesRef.current;

    const chart = createChart(container, {
      width: container.clientWidth,
      height,
      layout: {
        background: { type: ColorType.Solid, color: '#020617' },
        textColor: '#cbd5f5',
        fontSize: 11,
      },
      grid: {
        horzLines: { color: '#1e293b' },
        vertLines: { color: '#1e293b' },
      },
      rightPriceScale: { borderColor: '#334155' },
      timeScale: {
        borderColor: '#334155',
        timeVisible: false,
        secondsVisible: false,
      },
      crosshair: { mode: 0 },
      handleScale: false,
      handleScroll: false,
    });
    chartRef.current = chart;

    for (const line of lines) {
      const lineSeries = chart.addLineSeries({
        color: line.color,
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      lineMap.set(line.key, lineSeries);
    }

    const firstSeries = lineMap.values().next().value;
    if (firstSeries) {
      const ref = firstSeries as ISeriesApi<'Line'>;
      // Lock y-axis range so SVG overlay zones map cleanly to chart coordinates.
      if (typeof yAxisMin === 'number' && typeof yAxisMax === 'number') {
        ref.applyOptions({
          autoscaleInfoProvider: () => ({
            priceRange: { minValue: yAxisMin, maxValue: yAxisMax },
          }),
        });
      }
      for (const threshold of thresholds) {
        ref.createPriceLine({
          price: threshold.value,
          color: threshold.color,
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: true,
          title: threshold.label,
        });
      }
    }

    const resizeObserver = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (!entry) return;
      chart.applyOptions({ width: entry.contentRect.width });
    });
    resizeObserver.observe(container);

    setMounted(true);

    return () => {
      resizeObserver.disconnect();
      chart.remove();
      chartRef.current = null;
      lineMap.clear();
    };
  }, [height, lines, thresholds, yAxisMin, yAxisMax]);

  useEffect(() => {
    if (!mounted) return;
    const chart = chartRef.current;
    if (!chart) return;
    for (const line of lines) {
      const target = lineSeriesRef.current.get(line.key);
      if (target) target.setData(toLineData(series, line.key));
    }
    if (series.length > 0) chart.timeScale().fitContent();
  }, [series, lines, mounted]);

  const showZoneOverlay =
    typeof yAxisMin === 'number' && typeof yAxisMax === 'number';
  const yRange = showZoneOverlay ? (yAxisMax as number) - (yAxisMin as number) : 0;

  return (
    <div className="flex flex-col gap-2">
      <Legend lines={lines} thresholds={thresholds} />
      <div className="relative w-full">
        <div
          ref={containerRef}
          data-testid="indicator-bounded-line"
          role="img"
          aria-label={ariaLabel}
          className="w-full rounded-md border border-slate-800 bg-slate-950"
          style={{ height }}
        />
        {showZoneOverlay && yRange > 0 && (
          <svg
            aria-hidden="true"
            className="pointer-events-none absolute inset-0 h-full w-full"
            preserveAspectRatio="none"
            viewBox="0 0 100 100"
          >
            {thresholds
              .filter((t) => t.fillBetween)
              .map((t) => {
                const ratio = ((t.value - (yAxisMin as number)) / yRange) * 100;
                const yFromTop = 100 - ratio;
                if (t.fillBetween === 'above') {
                  return (
                    <rect
                      key={`${t.label}-above`}
                      x={0}
                      y={0}
                      width={100}
                      height={Math.max(0, yFromTop)}
                      fill={applyOpacity(t.color, 0.08)}
                    />
                  );
                }
                return (
                  <rect
                    key={`${t.label}-below`}
                    x={0}
                    y={yFromTop}
                    width={100}
                    height={Math.max(0, 100 - yFromTop)}
                    fill={applyOpacity(t.color, 0.08)}
                  />
                );
              })}
          </svg>
        )}
      </div>
    </div>
  );
}

interface LegendProps {
  lines: ReadonlyArray<BoundedLineDefinition>;
  thresholds: ReadonlyArray<BoundedLineThreshold>;
}

function Legend({ lines, thresholds }: LegendProps): JSX.Element {
  return (
    <ul className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-slate-300">
      {lines.map((line) => (
        <li key={line.key} className="flex items-center gap-1.5">
          <span
            aria-hidden="true"
            className="inline-block h-0.5 w-4"
            style={{ backgroundColor: line.color, height: 2 }}
          />
          <span>{line.label}</span>
        </li>
      ))}
      {thresholds.map((t) => (
        <li
          key={`threshold-${t.label}`}
          className="flex items-center gap-1.5 text-slate-400"
        >
          <span
            aria-hidden="true"
            className="inline-block h-0.5 w-4 border-t border-dashed"
            style={{ borderColor: t.color }}
          />
          <span>{t.label}</span>
        </li>
      ))}
    </ul>
  );
}
