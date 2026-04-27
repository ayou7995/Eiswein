import { useEffect, useRef } from 'react';
import {
  createChart,
  ColorType,
  type CandlestickData,
  type HistogramData,
  type IChartApi,
  type ISeriesApi,
  type Time,
} from 'lightweight-charts';
import { COLORS } from '../../lib/constants';
import type { AdDaySeriesResponse } from '../../api/marketIndicatorSeries';

// SPX OHLCV with three stacked panes inside a single chart:
//   1. Candles — traditional up=green / down=red coloring (price action)
//   2. Volume — colored by candle direction
//   3. A/D classification strip — independent green/red/gray bar that
//      flags 進貨/出貨/中性 per day, which is the *new* signal the user
//      can scan against the price action without their colors getting
//      confused with the classification.
//
// All three share the time axis. lightweight-charts v4 doesn't expose
// "panes" yet, so we use stacked priceScales with non-overlapping
// scaleMargins to fake the layout.

const CLASSIFICATION_COLOR: Record<'accum' | 'distrib' | 'neutral', string> = {
  accum: COLORS.SIGNAL_GREEN,
  distrib: COLORS.SIGNAL_RED,
  neutral: '#64748b',
};

const VOLUME_OPACITY_HEX = '99'; // 60% — keep volume secondary to price.

// scaleMargins control where each series sits inside the chart canvas.
// values are 0-1 fractions from top/bottom. They're tuned together so the
// three panes don't overlap, and the A/D strip is intentionally thin so
// it reads as a marginal annotation rather than a primary visual.
//
//  0 ────────────────────────────  top
//  │ price candles (≈63%)         │
//  │                              │
//  ├──── 0.65 ────────────────────┤  gap
//  │ volume bars (≈22%)           │
//  ├──── 0.89 ────────────────────┤  gap
//  │ ░░ A/D classification strip ░│  ≈5%
//  1 ────────────────────────────  bottom
const PRICE_PANE = { top: 0.02, bottom: 0.35 };
const VOLUME_PANE = { top: 0.67, bottom: 0.11 };
const AD_PANE = { top: 0.95, bottom: 0 };

// Each A/D classification bar uses the same value so they all render at
// the same height — the strip's job is to encode the classification
// color, not magnitude.
const AD_STRIP_VALUE = 1;

function toTime(dateString: string): Time {
  return dateString as unknown as Time;
}

interface SeriesItem extends AdDaySeriesResponse {}

function toCandleData(series: SeriesItem['series']): CandlestickData[] {
  const candles: CandlestickData[] = [];
  for (const row of series) {
    if (
      row.open === undefined ||
      row.open === null ||
      row.high === undefined ||
      row.high === null ||
      row.low === undefined ||
      row.low === null ||
      row.close === undefined ||
      row.close === null
    ) {
      continue;
    }
    candles.push({
      time: toTime(row.date),
      open: row.open,
      high: row.high,
      low: row.low,
      close: row.close,
    });
  }
  return candles;
}

function toVolumeData(series: SeriesItem['series']): HistogramData[] {
  const bars: HistogramData[] = [];
  for (const row of series) {
    if (
      row.volume === undefined ||
      row.volume === null ||
      row.open === undefined ||
      row.open === null ||
      row.close === undefined ||
      row.close === null
    ) {
      continue;
    }
    // Volume color follows price direction (traditional convention).
    const color = row.close >= row.open
      ? `${COLORS.SIGNAL_GREEN}${VOLUME_OPACITY_HEX}`
      : `${COLORS.SIGNAL_RED}${VOLUME_OPACITY_HEX}`;
    bars.push({
      time: toTime(row.date),
      value: row.volume,
      color,
    });
  }
  return bars;
}

function toAdStripData(series: SeriesItem['series']): HistogramData[] {
  return series.map((row) => ({
    time: toTime(row.date),
    value: AD_STRIP_VALUE,
    color: CLASSIFICATION_COLOR[row.classification],
  }));
}

export interface AdDayCandleClassificationChartProps {
  response: AdDaySeriesResponse;
}

export function AdDayCandleClassificationChart({
  response,
}: AdDayCandleClassificationChartProps): JSX.Element {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null);
  const adStripSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null);
  const latestResponseRef = useRef(response);
  latestResponseRef.current = response;

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return undefined;

    const chart = createChart(container, {
      width: container.clientWidth,
      height: 320,
      layout: {
        background: { type: ColorType.Solid, color: '#020617' },
        textColor: '#cbd5f5',
      },
      grid: {
        horzLines: { color: '#1e293b' },
        vertLines: { color: '#1e293b' },
      },
      rightPriceScale: { borderColor: '#334155', scaleMargins: PRICE_PANE },
      timeScale: {
        borderColor: '#334155',
        timeVisible: false,
        secondsVisible: false,
      },
      crosshair: { mode: 0 },
    });

    // Standard candle palette — up=green, down=red. Per-bar coloring
    // (the previous A/D-classification approach) is removed to keep
    // price action and accumulation/distribution signals independent.
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
      lastValueVisible: false,
      priceLineVisible: false,
    });
    chart.priceScale('volume').applyOptions({ scaleMargins: VOLUME_PANE });

    const adStripSeries = chart.addHistogramSeries({
      priceFormat: { type: 'price', precision: 0, minMove: 1 },
      priceScaleId: 'ad_strip',
      lastValueVisible: false,
      priceLineVisible: false,
      base: 0,
    });
    chart.priceScale('ad_strip').applyOptions({
      scaleMargins: AD_PANE,
      visible: false,
    });

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    volumeSeriesRef.current = volumeSeries;
    adStripSeriesRef.current = adStripSeries;

    candleSeries.setData(toCandleData(latestResponseRef.current.series));
    volumeSeries.setData(toVolumeData(latestResponseRef.current.series));
    adStripSeries.setData(toAdStripData(latestResponseRef.current.series));
    chart.timeScale().fitContent();

    const resize = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry !== undefined) chart.applyOptions({ width: entry.contentRect.width });
    });
    resize.observe(container);

    return () => {
      resize.disconnect();
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      volumeSeriesRef.current = null;
      adStripSeriesRef.current = null;
    };
  }, []);

  useEffect(() => {
    const candle = candleSeriesRef.current;
    const volume = volumeSeriesRef.current;
    const adStrip = adStripSeriesRef.current;
    const chart = chartRef.current;
    if (candle === null || volume === null || adStrip === null || chart === null) return;

    candle.setData(toCandleData(response.series));
    volume.setData(toVolumeData(response.series));
    adStrip.setData(toAdStripData(response.series));
    chart.timeScale().fitContent();
  }, [response]);

  return (
    <div className="flex flex-col gap-2">
      <div
        ref={containerRef}
        role="img"
        aria-label="A/D Day 圖表：上方 SPX 蠟燭、中間成交量、下方為當日 A/D 分類條"
        className="h-[320px] w-full"
      />
      <Legend />
    </div>
  );
}

function Legend(): JSX.Element {
  return (
    <div className="flex flex-col gap-1 text-[11px] text-slate-400">
      <p>上方為 SPX 蠟燭（漲綠跌紅）+ 成交量；下方色條為當日 A/D 分類：</p>
      <ul aria-hidden="true" className="flex flex-wrap gap-x-3 gap-y-1">
        <li className="flex items-center gap-1">
          <span
            className="inline-block h-2.5 w-2.5 rounded-sm"
            style={{ background: CLASSIFICATION_COLOR.accum }}
          />
          進貨日 (上漲 + 量擴)
        </li>
        <li className="flex items-center gap-1">
          <span
            className="inline-block h-2.5 w-2.5 rounded-sm"
            style={{ background: CLASSIFICATION_COLOR.distrib }}
          />
          出貨日 (下跌 + 量擴)
        </li>
        <li className="flex items-center gap-1">
          <span
            className="inline-block h-2.5 w-2.5 rounded-sm"
            style={{ background: CLASSIFICATION_COLOR.neutral }}
          />
          中性 (量縮或平盤)
        </li>
      </ul>
    </div>
  );
}
