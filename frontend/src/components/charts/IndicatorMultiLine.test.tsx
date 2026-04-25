import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';

const mocks = vi.hoisted(() => {
  return {
    setLineData: vi.fn(),
    setHistogramData: vi.fn(),
    setAreaData: vi.fn(),
    fitContent: vi.fn(),
    removeChart: vi.fn(),
    addLineSeries: vi.fn(),
    addHistogramSeries: vi.fn(),
    addAreaSeries: vi.fn(),
  };
});

vi.mock('lightweight-charts', () => {
  const lineSeries = { setData: mocks.setLineData, applyOptions: vi.fn() };
  const histSeries = { setData: mocks.setHistogramData, applyOptions: vi.fn() };
  const areaSeries = { setData: mocks.setAreaData, applyOptions: vi.fn() };
  const chart = {
    addLineSeries: mocks.addLineSeries.mockImplementation(() => lineSeries),
    addHistogramSeries: mocks.addHistogramSeries.mockImplementation(
      () => histSeries,
    ),
    addAreaSeries: mocks.addAreaSeries.mockImplementation(() => areaSeries),
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

import { IndicatorMultiLine } from './IndicatorMultiLine';

const series = Array.from({ length: 5 }, (_, i) => ({
  date: `2026-04-${String(i + 1).padStart(2, '0')}`,
  price: 100 + i,
  ma50: 95 + i,
  ma200: 90 + i,
}));

describe('IndicatorMultiLine', () => {
  beforeEach(() => {
    mocks.setLineData.mockClear();
    mocks.setHistogramData.mockClear();
    mocks.setAreaData.mockClear();
    mocks.fitContent.mockClear();
    mocks.removeChart.mockClear();
    mocks.addLineSeries.mockClear();
    mocks.addHistogramSeries.mockClear();
    mocks.addAreaSeries.mockClear();
  });

  it('renders the chart container, legend, and seeds line series data', () => {
    render(
      <IndicatorMultiLine
        series={series}
        lines={[
          { key: 'price', label: '收盤價', color: '#e2e8f0' },
          { key: 'ma50', label: '50 MA', color: '#38bdf8', style: 'dashed' },
        ]}
        ariaLabel="走勢"
      />,
    );
    expect(screen.getByTestId('indicator-multi-line')).toBeInTheDocument();
    expect(screen.getByText('收盤價')).toBeInTheDocument();
    expect(screen.getByText('50 MA')).toBeInTheDocument();
    expect(mocks.addLineSeries).toHaveBeenCalledTimes(2);
    expect(mocks.setLineData).toHaveBeenCalledTimes(2);
  });

  it('adds histogram + area series when histogram and shadedBand are provided', () => {
    render(
      <IndicatorMultiLine
        series={series}
        lines={[{ key: 'price', label: '價', color: '#e2e8f0' }]}
        histogram={{
          key: 'price',
          positiveColor: '#22c55e',
          negativeColor: '#ef4444',
        }}
        shadedBand={{
          upperKey: 'ma50',
          lowerKey: 'ma200',
          opacity: 0.2,
          color: '#38bdf8',
        }}
        ariaLabel="走勢"
      />,
    );
    expect(mocks.addHistogramSeries).toHaveBeenCalledTimes(1);
    expect(mocks.addAreaSeries).toHaveBeenCalledTimes(2);
    expect(mocks.setHistogramData).toHaveBeenCalledTimes(1);
    expect(mocks.setAreaData).toHaveBeenCalledTimes(2);
  });

  it('passes step lineType when a line is configured with step=true', () => {
    render(
      <IndicatorMultiLine
        series={series}
        lines={[{ key: 'price', label: '利率', color: '#facc15', step: true }]}
        ariaLabel="走勢"
      />,
    );
    expect(mocks.addLineSeries).toHaveBeenCalledTimes(1);
    const passed = mocks.addLineSeries.mock.calls[0]?.[0];
    expect(passed?.lineType).toBe(1);
  });

  it('cleans up the chart on unmount', () => {
    const { unmount } = render(
      <IndicatorMultiLine
        series={series}
        lines={[{ key: 'price', label: '價', color: '#e2e8f0' }]}
        ariaLabel="走勢"
      />,
    );
    unmount();
    expect(mocks.removeChart).toHaveBeenCalledTimes(1);
  });
});
