import { useEffect, useRef, useState } from 'react';
import {
  createChart,
  ColorType,
  LineStyle,
  LineType,
  type HistogramData,
  type IChartApi,
  type ISeriesApi,
  type LineData,
  type UTCTimestamp,
} from 'lightweight-charts';

export interface MultiLineSeriesRow {
  readonly date: string;
  // Null entries are tolerated for fields that may be undefined during
  // MA warm-up windows (the chart renders a gap at those points).
  readonly [key: string]: number | string | null;
}

export interface MultiLineDefinition {
  readonly key: string;
  readonly label: string;
  readonly color: string;
  readonly style?: 'solid' | 'dashed';
  readonly width?: 1 | 2;
  // step=true draws the line as discrete horizontal-then-vertical jumps
  // (LineType.WithSteps) — required for series like Fed Funds Rate where
  // smoothing between abrupt rate changes would misrepresent the data.
  readonly step?: boolean;
}

export interface MultiLineShadedBand {
  readonly upperKey: string;
  readonly lowerKey: string;
  readonly opacity: number;
  readonly color: string;
}

export interface MultiLineHistogram {
  readonly key: string;
  readonly positiveColor: string;
  readonly negativeColor: string;
}

export interface IndicatorMultiLineProps {
  readonly series: ReadonlyArray<MultiLineSeriesRow>;
  readonly lines: ReadonlyArray<MultiLineDefinition>;
  readonly shadedBand?: MultiLineShadedBand;
  readonly histogram?: MultiLineHistogram;
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

function readNumber(row: MultiLineSeriesRow, key: string): number | null {
  const raw = row[key];
  // Null is a valid value during MA warm-up — skipping the point is the
  // right rendering (lightweight-charts gracefully draws a gap).
  return typeof raw === 'number' && Number.isFinite(raw) ? raw : null;
}

function toLineData(
  series: ReadonlyArray<MultiLineSeriesRow>,
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

function toHistogramData(
  series: ReadonlyArray<MultiLineSeriesRow>,
  key: string,
  positiveColor: string,
  negativeColor: string,
): HistogramData[] {
  const out: HistogramData[] = [];
  for (const row of series) {
    const value = readNumber(row, key);
    if (value === null) continue;
    out.push({
      time: toUtcTimestamp(row.date),
      value,
      color: value >= 0 ? positiveColor : negativeColor,
    });
  }
  return out;
}

// lightweight-charts encodes hex+alpha as #rrggbbaa. Clamp opacity to [0,1] and
// emit an 8-char hex so consumers can pass tailwind-style colours unchanged.
function applyOpacity(hexColor: string, opacity: number): string {
  const clamped = Math.min(1, Math.max(0, opacity));
  const alpha = Math.round(clamped * 255)
    .toString(16)
    .padStart(2, '0');
  if (/^#[0-9a-fA-F]{6}$/.test(hexColor)) return `${hexColor}${alpha}`;
  return hexColor;
}

export function IndicatorMultiLine({
  series,
  lines,
  shadedBand,
  histogram,
  height = 220,
  ariaLabel,
}: IndicatorMultiLineProps): JSX.Element {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const lineSeriesRef = useRef<Map<string, ISeriesApi<'Line'>>>(new Map());
  const bandUpperRef = useRef<ISeriesApi<'Area'> | null>(null);
  const bandLowerRef = useRef<ISeriesApi<'Area'> | null>(null);
  const histogramRef = useRef<ISeriesApi<'Histogram'> | null>(null);
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

    if (shadedBand) {
      // Two stacked area series approximate a band fill: the upper line
      // is filled down with semi-transparent colour, and the lower area
      // overpaints the bottom portion in the chart background. Where the
      // top fill remains visible, you see the band envelope.
      const upper = chart.addAreaSeries({
        lineColor: applyOpacity(shadedBand.color, 0.6),
        topColor: applyOpacity(shadedBand.color, shadedBand.opacity),
        bottomColor: applyOpacity(shadedBand.color, shadedBand.opacity),
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      const lower = chart.addAreaSeries({
        lineColor: applyOpacity(shadedBand.color, 0.6),
        topColor: '#02061700',
        bottomColor: '#020617ff',
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      bandUpperRef.current = upper;
      bandLowerRef.current = lower;
    }

    if (histogram) {
      const hist = chart.addHistogramSeries({
        priceLineVisible: false,
        lastValueVisible: false,
        priceFormat: { type: 'price', precision: 4, minMove: 0.0001 },
      });
      histogramRef.current = hist;
    }

    for (const line of lines) {
      const series = chart.addLineSeries({
        color: line.color,
        lineWidth: line.width ?? 2,
        lineStyle: line.style === 'dashed' ? LineStyle.Dashed : LineStyle.Solid,
        lineType: line.step ? LineType.WithSteps : LineType.Simple,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      lineMap.set(line.key, series);
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
      bandUpperRef.current = null;
      bandLowerRef.current = null;
      histogramRef.current = null;
    };
  }, [height, lines, shadedBand, histogram]);

  useEffect(() => {
    if (!mounted) return;
    const chart = chartRef.current;
    if (!chart) return;

    if (shadedBand && bandUpperRef.current && bandLowerRef.current) {
      bandUpperRef.current.setData(toLineData(series, shadedBand.upperKey));
      bandLowerRef.current.setData(toLineData(series, shadedBand.lowerKey));
    }
    if (histogram && histogramRef.current) {
      histogramRef.current.setData(
        toHistogramData(
          series,
          histogram.key,
          histogram.positiveColor,
          histogram.negativeColor,
        ),
      );
    }
    for (const line of lines) {
      const target = lineSeriesRef.current.get(line.key);
      if (target) target.setData(toLineData(series, line.key));
    }
    if (series.length > 0) chart.timeScale().fitContent();
  }, [series, lines, shadedBand, histogram, mounted]);

  return (
    <div className="flex flex-col gap-2">
      <Legend
        lines={lines}
        {...(histogram ? { histogram } : {})}
        {...(shadedBand ? { shadedBand } : {})}
      />
      <div
        ref={containerRef}
        data-testid="indicator-multi-line"
        role="img"
        aria-label={ariaLabel}
        className="w-full rounded-md border border-slate-800 bg-slate-950"
        style={{ height }}
      />
    </div>
  );
}

interface LegendProps {
  lines: ReadonlyArray<MultiLineDefinition>;
  histogram?: MultiLineHistogram;
  shadedBand?: MultiLineShadedBand;
}

function Legend({ lines, histogram, shadedBand }: LegendProps): JSX.Element {
  return (
    <ul className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-slate-300">
      {lines.map((line) => (
        <li key={line.key} className="flex items-center gap-1.5">
          <span
            aria-hidden="true"
            className="inline-block h-0.5 w-4"
            style={{
              backgroundColor: line.color,
              borderTop:
                line.style === 'dashed'
                  ? `1px dashed ${line.color}`
                  : undefined,
              borderBottom: 'none',
              height: line.style === 'dashed' ? 0 : 2,
            }}
          />
          <span>{line.label}</span>
        </li>
      ))}
      {shadedBand && (
        <li className="flex items-center gap-1.5">
          <span
            aria-hidden="true"
            className="inline-block h-3 w-3 rounded-sm"
            style={{
              backgroundColor: shadedBand.color,
              opacity: shadedBand.opacity,
            }}
          />
          <span>BB 通道</span>
        </li>
      )}
      {histogram && (
        <li className="flex items-center gap-1.5">
          <span
            aria-hidden="true"
            className="inline-block h-3 w-3 rounded-sm"
            style={{ backgroundColor: histogram.positiveColor }}
          />
          <span>柱狀圖</span>
        </li>
      )}
    </ul>
  );
}
