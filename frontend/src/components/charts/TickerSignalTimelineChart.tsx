import { useEffect, useRef, useState } from 'react';
import {
  createChart,
  ColorType,
  LineStyle,
  type IChartApi,
  type ISeriesApi,
  type LineData,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
} from 'lightweight-charts';
import type { TickerSignalPoint } from '../../api/history';

export interface TickerSignalTimelineChartProps {
  readonly data: ReadonlyArray<TickerSignalPoint>;
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

// Marker preset per ActionCategory. Only directional actions get a marker
// — putting a 持有/觀望 dot on every bar would overwhelm the chart and
// dilute the meaningful entry/exit cues. Color cues mirror the dashboard
// SignalBadge so the user's mental model stays consistent.
const MARKER_PRESETS: Record<string, {
  position: 'aboveBar' | 'belowBar';
  shape: 'arrowUp' | 'arrowDown' | 'circle';
  color: string;
  text: string;
} | null> = {
  strong_buy: {
    position: 'belowBar',
    shape: 'arrowUp',
    color: '#22c55e',
    text: '強買',
  },
  buy: {
    position: 'belowBar',
    shape: 'arrowUp',
    color: '#86efac',
    text: '買',
  },
  reduce: {
    position: 'aboveBar',
    shape: 'arrowDown',
    color: '#facc15',
    text: '減',
  },
  exit: {
    position: 'aboveBar',
    shape: 'arrowDown',
    color: '#ef4444',
    text: '出',
  },
  // Non-directional actions stay null — no marker at all.
  hold: null,
  watch: null,
};

export function TickerSignalTimelineChart({
  data,
  height = 280,
  ariaLabel,
}: TickerSignalTimelineChartProps): JSX.Element {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const lineSeriesRef = useRef<ISeriesApi<'Line'> | null>(null);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return undefined;

    const chart = createChart(container, {
      width: container.clientWidth,
      height,
      layout: {
        background: { type: ColorType.Solid, color: '#ffffff' },
        textColor: '#44403c',
        fontSize: 11,
      },
      grid: {
        horzLines: { color: 'rgba(0,0,0,0.06)' },
        vertLines: { color: 'rgba(0,0,0,0.06)' },
      },
      rightPriceScale: { borderColor: 'rgba(0,0,0,0.12)' },
      timeScale: {
        borderColor: 'rgba(0,0,0,0.12)',
        timeVisible: false,
        secondsVisible: false,
      },
      crosshair: { mode: 0 },
    });
    chartRef.current = chart;

    const lineSeries = chart.addLineSeries({
      color: '#1c1917',
      lineWidth: 2,
      lineStyle: LineStyle.Solid,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    lineSeriesRef.current = lineSeries;

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
      lineSeriesRef.current = null;
    };
  }, [height]);

  useEffect(() => {
    if (!mounted) return;
    const chart = chartRef.current;
    const series = lineSeriesRef.current;
    if (!chart || !series) return;

    const lineData: LineData[] = data
      .filter((d) => Number.isFinite(d.close))
      .map((d) => ({
        time: toUtcTimestamp(d.date),
        value: d.close,
      }));

    // Lightweight-charts requires markers in chronological order and
    // de-duplicated by `time`. Snapshots are already 1-per-day and we
    // sort defensively here so the runtime won't reject.
    const markers: SeriesMarker<Time>[] = data
      .map((d): SeriesMarker<Time> | null => {
        const preset = MARKER_PRESETS[d.action];
        if (!preset) return null;
        return {
          time: toUtcTimestamp(d.date),
          position: preset.position,
          shape: preset.shape,
          color: preset.color,
          text: preset.text,
        };
      })
      .filter((m): m is SeriesMarker<Time> => m !== null)
      .sort((a, b) => Number(a.time) - Number(b.time));

    series.setData(lineData);
    series.setMarkers(markers);
    if (lineData.length > 0) chart.timeScale().fitContent();
  }, [data, mounted]);

  return (
    <div className="flex flex-col gap-2">
      <ul className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-stone-700">
        <li className="flex items-center gap-1.5">
          <span aria-hidden="true" className="text-signal-green">▲</span>
          <span>強買 / 買</span>
        </li>
        <li className="flex items-center gap-1.5">
          <span aria-hidden="true" className="text-signal-yellow">▼</span>
          <span>減倉</span>
        </li>
        <li className="flex items-center gap-1.5">
          <span aria-hidden="true" className="text-signal-red">▼</span>
          <span>出場</span>
        </li>
        <li className="flex items-center gap-1.5 text-stone-400">
          <span>（持有 / 觀望日不顯示 marker — 避免雜訊）</span>
        </li>
      </ul>
      <div
        ref={containerRef}
        data-testid="ticker-signal-timeline-chart"
        role="img"
        aria-label={ariaLabel}
        className="w-full rounded-md border border-stone-200 bg-stone-50"
        style={{ height }}
      />
    </div>
  );
}
