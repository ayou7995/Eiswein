import { useEffect, useRef } from 'react';
import {
  createChart,
  ColorType,
  LineStyle,
  type IChartApi,
  type ISeriesApi,
  type LineData,
  type Time,
} from 'lightweight-charts';
import type { YieldSpreadSeriesResponse } from '../../api/marketIndicatorSeries';

// 10Y-2Y rendered as TWO panes inside one chart so the spread (≈0.5)
// doesn't get squashed against the 10Y/2Y absolute-yield lines (≈4%).
//
//   ┌─────────────────────────────┐
//   │ Top pane — 10Y / 2Y         │  ≈55% height
//   │ scale fits ~3.5%-5%         │
//   ├─────────────────────────────┤
//   │ Bottom pane — spread + 0    │  ≈35% height
//   │ scale fits ~-1%-+1%         │
//   └─────────────────────────────┘
//
// lightweight-charts v4 doesn't expose a panes API, so we stack two
// independent priceScales with non-overlapping margins (same trick
// AdDayCandleClassificationChart uses).

const COLORS = {
  ten: '#38bdf8',
  two: '#f59e0b',
  spread: '#e2e8f0',
  zero: '#ef4444',
};

const YIELD_PANE = { top: 0.05, bottom: 0.42 };
const SPREAD_PANE = { top: 0.62, bottom: 0.05 };

function toTime(dateString: string): Time {
  return dateString as unknown as Time;
}

function toLineData(
  series: YieldSpreadSeriesResponse['series'],
  key: 'ten_year' | 'two_year' | 'spread',
): LineData[] {
  return series.map((row) => ({
    time: toTime(row.date),
    value: row[key],
  }));
}

export interface YieldSpreadDualPaneChartProps {
  response: YieldSpreadSeriesResponse;
}

export function YieldSpreadDualPaneChart({
  response,
}: YieldSpreadDualPaneChartProps): JSX.Element {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const tenSeriesRef = useRef<ISeriesApi<'Line'> | null>(null);
  const twoSeriesRef = useRef<ISeriesApi<'Line'> | null>(null);
  const spreadSeriesRef = useRef<ISeriesApi<'Line'> | null>(null);
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
      rightPriceScale: { borderColor: '#334155', scaleMargins: YIELD_PANE },
      timeScale: {
        borderColor: '#334155',
        timeVisible: false,
        secondsVisible: false,
      },
      crosshair: { mode: 0 },
    });

    const tenSeries = chart.addLineSeries({
      color: COLORS.ten,
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: true,
    });
    const twoSeries = chart.addLineSeries({
      color: COLORS.two,
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: true,
    });

    const spreadSeries = chart.addLineSeries({
      color: COLORS.spread,
      lineWidth: 2,
      priceScaleId: 'spread',
      priceLineVisible: false,
      lastValueVisible: true,
    });
    chart.priceScale('spread').applyOptions({
      borderColor: '#334155',
      scaleMargins: SPREAD_PANE,
    });
    // The 0-line is the inversion threshold — show it on the spread pane
    // as a dashed horizontal price line so the user can read the gap from
    // current spread to inversion at a glance.
    spreadSeries.createPriceLine({
      price: 0,
      color: COLORS.zero,
      lineWidth: 1,
      lineStyle: LineStyle.Dashed,
      axisLabelVisible: true,
      title: '倒掛線',
    });

    chartRef.current = chart;
    tenSeriesRef.current = tenSeries;
    twoSeriesRef.current = twoSeries;
    spreadSeriesRef.current = spreadSeries;

    tenSeries.setData(toLineData(latestResponseRef.current.series, 'ten_year'));
    twoSeries.setData(toLineData(latestResponseRef.current.series, 'two_year'));
    spreadSeries.setData(toLineData(latestResponseRef.current.series, 'spread'));
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
      tenSeriesRef.current = null;
      twoSeriesRef.current = null;
      spreadSeriesRef.current = null;
    };
  }, []);

  useEffect(() => {
    const ten = tenSeriesRef.current;
    const two = twoSeriesRef.current;
    const spread = spreadSeriesRef.current;
    const chart = chartRef.current;
    if (ten === null || two === null || spread === null || chart === null) return;
    ten.setData(toLineData(response.series, 'ten_year'));
    two.setData(toLineData(response.series, 'two_year'));
    spread.setData(toLineData(response.series, 'spread'));
    chart.timeScale().fitContent();
  }, [response]);

  return (
    <div className="flex flex-col gap-2">
      <div
        ref={containerRef}
        role="img"
        aria-label="10Y-2Y 利差圖：上方 10Y / 2Y 殖利率，下方利差 + 倒掛線"
        className="h-[320px] w-full"
      />
      <Legend />
    </div>
  );
}

function Legend(): JSX.Element {
  return (
    <ul
      aria-hidden="true"
      className="flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-slate-400"
    >
      <li className="flex items-center gap-1">
        <span className="inline-block h-0.5 w-4" style={{ background: COLORS.ten }} />
        10Y 殖利率
      </li>
      <li className="flex items-center gap-1">
        <span className="inline-block h-0.5 w-4" style={{ background: COLORS.two }} />
        2Y 殖利率
      </li>
      <li className="flex items-center gap-1">
        <span className="inline-block h-0.5 w-4" style={{ background: COLORS.spread }} />
        10Y-2Y 利差
      </li>
      <li className="flex items-center gap-1">
        <span
          className="inline-block h-0.5 w-4 border-t border-dashed"
          style={{ borderColor: COLORS.zero }}
        />
        倒掛線 (0)
      </li>
    </ul>
  );
}
