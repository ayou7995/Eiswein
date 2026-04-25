import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';

const mocks = vi.hoisted(() => {
  return {
    setLineData: vi.fn(),
    fitContent: vi.fn(),
    removeChart: vi.fn(),
    addLineSeries: vi.fn(),
    createPriceLine: vi.fn(),
    applyOptions: vi.fn(),
  };
});

vi.mock('lightweight-charts', () => {
  const lineSeries = {
    setData: mocks.setLineData,
    applyOptions: mocks.applyOptions,
    createPriceLine: mocks.createPriceLine,
  };
  const chart = {
    addLineSeries: mocks.addLineSeries.mockImplementation(() => lineSeries),
    timeScale: vi.fn(() => ({ fitContent: mocks.fitContent })),
    applyOptions: vi.fn(),
    remove: mocks.removeChart,
  };
  return {
    createChart: vi.fn(() => chart),
    ColorType: { Solid: 'solid' },
    LineStyle: { Solid: 0, Dashed: 1 },
  };
});

import { IndicatorBoundedLine } from './IndicatorBoundedLine';

const series = Array.from({ length: 5 }, (_, i) => ({
  date: `2026-04-${String(i + 1).padStart(2, '0')}`,
  daily: 50 + i,
  weekly: 55 + i,
}));

describe('IndicatorBoundedLine', () => {
  beforeEach(() => {
    mocks.setLineData.mockClear();
    mocks.fitContent.mockClear();
    mocks.removeChart.mockClear();
    mocks.addLineSeries.mockClear();
    mocks.createPriceLine.mockClear();
    mocks.applyOptions.mockClear();
  });

  it('renders the chart, legend lines, and threshold labels', () => {
    render(
      <IndicatorBoundedLine
        series={series}
        lines={[
          { key: 'daily', label: '日 RSI', color: '#38bdf8' },
          { key: 'weekly', label: '週 RSI', color: '#a78bfa' },
        ]}
        thresholds={[
          { value: 30, label: '超賣', color: '#22c55e', fillBetween: 'below' },
          { value: 70, label: '超買', color: '#ef4444', fillBetween: 'above' },
        ]}
        yAxisMin={0}
        yAxisMax={100}
        ariaLabel="RSI"
      />,
    );
    expect(screen.getByTestId('indicator-bounded-line')).toBeInTheDocument();
    expect(screen.getByText('日 RSI')).toBeInTheDocument();
    expect(screen.getByText('週 RSI')).toBeInTheDocument();
    expect(screen.getByText('超賣')).toBeInTheDocument();
    expect(screen.getByText('超買')).toBeInTheDocument();
    expect(mocks.addLineSeries).toHaveBeenCalledTimes(2);
    expect(mocks.createPriceLine).toHaveBeenCalledTimes(2);
    expect(mocks.setLineData).toHaveBeenCalledTimes(2);
  });

  it('cleans up the chart on unmount', () => {
    const { unmount } = render(
      <IndicatorBoundedLine
        series={series}
        lines={[{ key: 'daily', label: '日 RSI', color: '#38bdf8' }]}
        thresholds={[]}
        ariaLabel="RSI"
      />,
    );
    unmount();
    expect(mocks.removeChart).toHaveBeenCalledTimes(1);
  });
});
