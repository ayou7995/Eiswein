import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';

const mocks = vi.hoisted(() => {
  return {
    setHistogramData: vi.fn(),
    setLineData: vi.fn(),
    fitContent: vi.fn(),
    removeChart: vi.fn(),
    addHistogramSeries: vi.fn(),
    addLineSeries: vi.fn(),
  };
});

vi.mock('lightweight-charts', () => {
  const histSeries = { setData: mocks.setHistogramData, applyOptions: vi.fn() };
  const lineSeries = { setData: mocks.setLineData, applyOptions: vi.fn() };
  const chart = {
    addHistogramSeries: mocks.addHistogramSeries.mockImplementation(() => histSeries),
    addLineSeries: mocks.addLineSeries.mockImplementation(() => lineSeries),
    timeScale: vi.fn(() => ({ fitContent: mocks.fitContent })),
    applyOptions: vi.fn(),
    remove: mocks.removeChart,
  };
  return {
    createChart: vi.fn(() => chart),
    ColorType: { Solid: 'solid' },
    LineStyle: { Solid: 0, Dashed: 1 },
    LineType: { Simple: 0, WithSteps: 1 },
  };
});

import { IndicatorVolumeBars } from './IndicatorVolumeBars';

const COLORS = {
  up: '#22c55e',
  down: '#ef4444',
  flat: '#475569',
  average: '#facc15',
};

describe('IndicatorVolumeBars', () => {
  beforeEach(() => {
    mocks.setHistogramData.mockClear();
    mocks.setLineData.mockClear();
    mocks.fitContent.mockClear();
    mocks.removeChart.mockClear();
    mocks.addHistogramSeries.mockClear();
    mocks.addLineSeries.mockClear();
  });

  it('renders the chart, legend, and seeds histogram + average line series', () => {
    const series = [
      { date: '2026-04-20', volume: 1_000_000, price_change_pct: 0.012, avg_volume_20d: 950_000 },
      { date: '2026-04-21', volume: 1_300_000, price_change_pct: -0.008, avg_volume_20d: 970_000 },
      { date: '2026-04-22', volume: 700_000, price_change_pct: 0, avg_volume_20d: 980_000 },
    ];

    render(
      <IndicatorVolumeBars
        series={series}
        upColor={COLORS.up}
        downColor={COLORS.down}
        flatColor={COLORS.flat}
        averageLineColor={COLORS.average}
        ariaLabel="成交量 60 日"
      />,
    );

    expect(screen.getByTestId('indicator-volume-bars')).toBeInTheDocument();
    expect(screen.getByText('上漲日成交量')).toBeInTheDocument();
    expect(screen.getByText('下跌日成交量')).toBeInTheDocument();
    expect(screen.getByText('20 日均量')).toBeInTheDocument();
    expect(mocks.addHistogramSeries).toHaveBeenCalledTimes(1);
    expect(mocks.addLineSeries).toHaveBeenCalledTimes(1);
    expect(mocks.setHistogramData).toHaveBeenCalledTimes(1);
    expect(mocks.setLineData).toHaveBeenCalledTimes(1);

    const histPayload = mocks.setHistogramData.mock.calls[0]?.[0] as Array<{
      color: string;
    }>;
    const upBars = histPayload.filter((b) => b.color === COLORS.up).length;
    const downBars = histPayload.filter((b) => b.color === COLORS.down).length;
    const flatBars = histPayload.filter((b) => b.color === COLORS.flat).length;
    expect(upBars).toBe(1);
    expect(downBars).toBe(1);
    expect(flatBars).toBe(1);
  });

  it('cleans up the chart on unmount', () => {
    const { unmount } = render(
      <IndicatorVolumeBars
        series={[]}
        upColor={COLORS.up}
        downColor={COLORS.down}
        flatColor={COLORS.flat}
        averageLineColor={COLORS.average}
        ariaLabel="成交量 60 日"
      />,
    );
    unmount();
    expect(mocks.removeChart).toHaveBeenCalledTimes(1);
  });
});
