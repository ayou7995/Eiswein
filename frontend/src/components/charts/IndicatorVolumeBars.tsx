import { useEffect, useRef, useState } from 'react';
import {
  createChart,
  ColorType,
  LineStyle,
  type HistogramData,
  type IChartApi,
  type ISeriesApi,
  type LineData,
  type UTCTimestamp,
} from 'lightweight-charts';

export interface VolumeBarsRow {
  readonly date: string;
  readonly volume: number;
  // Nullable on the warmup bars (see schema in tickerIndicatorSeries.ts).
  readonly price_change_pct: number | null;
  readonly avg_volume_20d: number | null;
}

export interface IndicatorVolumeBarsProps {
  readonly series: ReadonlyArray<VolumeBarsRow>;
  readonly upColor: string;
  readonly downColor: string;
  readonly flatColor: string;
  readonly averageLineColor: string;
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

function colorFor(
  changePct: number | null,
  upColor: string,
  downColor: string,
  flatColor: string,
): string {
  if (changePct === null) return flatColor;
  if (changePct > 0) return upColor;
  if (changePct < 0) return downColor;
  return flatColor;
}

export function IndicatorVolumeBars({
  series,
  upColor,
  downColor,
  flatColor,
  averageLineColor,
  height = 200,
  ariaLabel,
}: IndicatorVolumeBarsProps): JSX.Element {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const histogramRef = useRef<ISeriesApi<'Histogram'> | null>(null);
  const averageLineRef = useRef<ISeriesApi<'Line'> | null>(null);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return undefined;

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

    const histogram = chart.addHistogramSeries({
      priceLineVisible: false,
      lastValueVisible: false,
      priceFormat: { type: 'volume' },
    });
    histogramRef.current = histogram;

    // Average line shares the histogram's price scale so the user can see
    // today's volume relative to the 20d average without a confusing dual axis.
    const averageLine = chart.addLineSeries({
      color: averageLineColor,
      lineWidth: 1,
      lineStyle: LineStyle.Solid,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    averageLineRef.current = averageLine;

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
      histogramRef.current = null;
      averageLineRef.current = null;
    };
  }, [height, averageLineColor]);

  useEffect(() => {
    if (!mounted) return;
    const chart = chartRef.current;
    const histogram = histogramRef.current;
    const averageLine = averageLineRef.current;
    if (!chart || !histogram || !averageLine) return;

    const histData: HistogramData[] = [];
    const lineData: LineData[] = [];
    for (const row of series) {
      if (!Number.isFinite(row.volume)) continue;
      const time = toUtcTimestamp(row.date);
      histData.push({
        time,
        value: row.volume,
        color: colorFor(row.price_change_pct, upColor, downColor, flatColor),
      });
      if (row.avg_volume_20d !== null && Number.isFinite(row.avg_volume_20d)) {
        lineData.push({ time, value: row.avg_volume_20d });
      }
    }
    histogram.setData(histData);
    averageLine.setData(lineData);
    if (histData.length > 0) chart.timeScale().fitContent();
  }, [series, upColor, downColor, flatColor, mounted]);

  return (
    <div className="flex flex-col gap-2">
      <ul className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-slate-300">
        <li className="flex items-center gap-1.5">
          <span
            aria-hidden="true"
            className="inline-block h-3 w-3 rounded-sm"
            style={{ backgroundColor: upColor }}
          />
          <span>上漲日成交量</span>
        </li>
        <li className="flex items-center gap-1.5">
          <span
            aria-hidden="true"
            className="inline-block h-3 w-3 rounded-sm"
            style={{ backgroundColor: downColor }}
          />
          <span>下跌日成交量</span>
        </li>
        <li className="flex items-center gap-1.5 text-slate-400">
          <span
            aria-hidden="true"
            className="inline-block h-0.5 w-4"
            style={{ backgroundColor: averageLineColor, height: 2 }}
          />
          <span>20 日均量</span>
        </li>
      </ul>
      <div
        ref={containerRef}
        data-testid="indicator-volume-bars"
        role="img"
        aria-label={ariaLabel}
        className="w-full rounded-md border border-slate-800 bg-slate-950"
        style={{ height }}
      />
    </div>
  );
}
