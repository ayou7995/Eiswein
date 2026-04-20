import { useEffect, useRef, useState } from 'react';
import {
  createChart,
  ColorType,
  type CandlestickData,
  type HistogramData,
  type IChartApi,
  type ISeriesApi,
  type LineData,
  type UTCTimestamp,
} from 'lightweight-charts';
import { COLORS } from '../../lib/constants';
import { PRICE_RANGES, type PriceBar, type PriceRange } from '../../api/tickerPrices';
import { LoadingSpinner } from '../LoadingSpinner';

export interface CandlestickChartProps {
  bars: readonly PriceBar[];
  range: PriceRange;
  onRangeChange: (range: PriceRange) => void;
  loading?: boolean;
  emptyMessage?: string;
  // Show optional MA50/MA200 overlays. Values are computed client-side from
  // bars — see computeMovingAverage. Backend ships them in indicator.detail
  // for reference; duplicating that trip for the chart isn't worth it.
  showMovingAverages?: boolean;
}

// Convert YYYY-MM-DD to lightweight-charts' UTCTimestamp (seconds since epoch,
// UTC midnight). Using a branded nominal type requires the cast at the
// boundary — this is the one allowed cast site (kept to a single helper).
function toUtcTimestamp(dateString: string): UTCTimestamp {
  const seconds = Math.floor(Date.UTC(
    Number.parseInt(dateString.slice(0, 4), 10),
    Number.parseInt(dateString.slice(5, 7), 10) - 1,
    Number.parseInt(dateString.slice(8, 10), 10),
  ) / 1000);
  return seconds as UTCTimestamp;
}

export function computeMovingAverage(
  bars: readonly PriceBar[],
  window: number,
): LineData[] {
  if (window <= 0 || bars.length < window) return [];
  const result: LineData[] = [];
  let rollingSum = 0;
  for (let i = 0; i < bars.length; i += 1) {
    const bar = bars[i];
    if (!bar) continue;
    rollingSum += bar.close;
    if (i >= window) {
      const dropped = bars[i - window];
      if (dropped) rollingSum -= dropped.close;
    }
    if (i >= window - 1) {
      result.push({
        time: toUtcTimestamp(bar.date),
        value: rollingSum / window,
      });
    }
  }
  return result;
}

function toCandlestickData(bars: readonly PriceBar[]): CandlestickData[] {
  return bars.map((bar) => ({
    time: toUtcTimestamp(bar.date),
    open: bar.open,
    high: bar.high,
    low: bar.low,
    close: bar.close,
  }));
}

function toVolumeData(bars: readonly PriceBar[]): HistogramData[] {
  return bars.map((bar) => ({
    time: toUtcTimestamp(bar.date),
    value: bar.volume,
    color: bar.close >= bar.open ? `${COLORS.SIGNAL_GREEN}80` : `${COLORS.SIGNAL_RED}80`,
  }));
}

export function CandlestickChart({
  bars,
  range,
  onRangeChange,
  loading = false,
  emptyMessage = '價格資料準備中',
  showMovingAverages = true,
}: CandlestickChartProps): JSX.Element {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null);
  const ma50SeriesRef = useRef<ISeriesApi<'Line'> | null>(null);
  const ma200SeriesRef = useRef<ISeriesApi<'Line'> | null>(null);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return undefined;

    const chart = createChart(container, {
      width: container.clientWidth,
      height: 360,
      layout: {
        background: { type: ColorType.Solid, color: '#020617' },
        textColor: '#cbd5f5',
      },
      grid: {
        horzLines: { color: '#1e293b' },
        vertLines: { color: '#1e293b' },
      },
      rightPriceScale: { borderColor: '#334155' },
      timeScale: { borderColor: '#334155', timeVisible: false, secondsVisible: false },
      crosshair: { mode: 0 },
    });

    const candleSeries = chart.addCandlestickSeries({
      upColor: COLORS.SIGNAL_GREEN,
      downColor: COLORS.SIGNAL_RED,
      borderUpColor: COLORS.SIGNAL_GREEN,
      borderDownColor: COLORS.SIGNAL_RED,
      wickUpColor: COLORS.SIGNAL_GREEN,
      wickDownColor: COLORS.SIGNAL_RED,
    });
    const volumeSeries = chart.addHistogramSeries({
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume',
    });
    // Volume pane lives in its own scale at the bottom of the chart.
    chart.priceScale('volume').applyOptions({
      scaleMargins: { top: 0.8, bottom: 0 },
    });
    const ma50 = chart.addLineSeries({
      color: '#38bdf8',
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    const ma200 = chart.addLineSeries({
      color: '#facc15',
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
    });

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    volumeSeriesRef.current = volumeSeries;
    ma50SeriesRef.current = ma50;
    ma200SeriesRef.current = ma200;

    const resizeObserver = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (!entry) return;
      const { width } = entry.contentRect;
      chart.applyOptions({ width });
    });
    resizeObserver.observe(container);

    setMounted(true);

    return () => {
      resizeObserver.disconnect();
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      volumeSeriesRef.current = null;
      ma50SeriesRef.current = null;
      ma200SeriesRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!mounted) return;
    const candle = candleSeriesRef.current;
    const volume = volumeSeriesRef.current;
    const ma50 = ma50SeriesRef.current;
    const ma200 = ma200SeriesRef.current;
    const chart = chartRef.current;
    if (!candle || !volume || !ma50 || !ma200 || !chart) return;

    candle.setData(toCandlestickData(bars));
    volume.setData(toVolumeData(bars));
    if (showMovingAverages) {
      ma50.setData(computeMovingAverage(bars, 50));
      ma200.setData(computeMovingAverage(bars, 200));
    } else {
      ma50.setData([]);
      ma200.setData([]);
    }
    if (bars.length > 0) chart.timeScale().fitContent();
  }, [bars, showMovingAverages, mounted]);

  return (
    <section aria-labelledby="candlestick-chart-heading" className="flex flex-col gap-3">
      <header className="flex items-center justify-between gap-2">
        <h2 id="candlestick-chart-heading" className="sr-only">
          價格走勢圖
        </h2>
        <RangeSelector range={range} onChange={onRangeChange} />
      </header>
      <div className="relative rounded-lg border border-slate-800 bg-slate-950">
        <div
          ref={containerRef}
          data-testid="candlestick-chart-container"
          aria-label="K 線圖，含 50MA、200MA、交易量"
          role="img"
          className="h-[360px] w-full"
        />
        {loading && (
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center bg-slate-950/60">
            <LoadingSpinner label="載入價格資料…" />
          </div>
        )}
        {!loading && bars.length === 0 && (
          <div
            role="status"
            className="pointer-events-none absolute inset-0 flex items-center justify-center text-sm text-slate-400"
          >
            {emptyMessage}
          </div>
        )}
      </div>
    </section>
  );
}

interface RangeSelectorProps {
  range: PriceRange;
  onChange: (next: PriceRange) => void;
}

function RangeSelector({ range, onChange }: RangeSelectorProps): JSX.Element {
  return (
    <div
      role="radiogroup"
      aria-label="價格區間"
      className="inline-flex rounded-md border border-slate-700 bg-slate-900/40 p-0.5"
    >
      {PRICE_RANGES.map((option) => {
        const active = option === range;
        return (
          <button
            key={option}
            type="button"
            role="radio"
            aria-checked={active}
            data-testid={`range-${option}`}
            onClick={() => onChange(option)}
            className={`rounded px-3 py-1 text-xs font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400 ${
              active
                ? 'bg-sky-600 text-white'
                : 'text-slate-300 hover:bg-slate-800 hover:text-white'
            }`}
          >
            {option}
          </button>
        );
      })}
    </div>
  );
}
