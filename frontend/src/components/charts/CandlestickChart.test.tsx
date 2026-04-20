import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const mocks = vi.hoisted(() => {
  const setDataCandle = vi.fn();
  const setDataVolume = vi.fn();
  const setDataLine = vi.fn();
  const applyOptions = vi.fn();
  const fitContent = vi.fn();
  const removeChart = vi.fn();
  return {
    setDataCandle,
    setDataVolume,
    setDataLine,
    applyOptions,
    fitContent,
    removeChart,
  };
});

vi.mock('lightweight-charts', () => {
  const makeSeries = (setData: () => void): unknown => ({
    setData,
    applyOptions: vi.fn(),
  });
  const chartInstance = {
    addCandlestickSeries: vi.fn(() => makeSeries(mocks.setDataCandle)),
    addHistogramSeries: vi.fn(() => makeSeries(mocks.setDataVolume)),
    addLineSeries: vi.fn(() => makeSeries(mocks.setDataLine)),
    priceScale: vi.fn(() => ({ applyOptions: mocks.applyOptions })),
    timeScale: vi.fn(() => ({ fitContent: mocks.fitContent })),
    applyOptions: mocks.applyOptions,
    remove: mocks.removeChart,
  };
  return {
    createChart: vi.fn(() => chartInstance),
    ColorType: { Solid: 'solid' },
  };
});

import { CandlestickChart, computeMovingAverage } from './CandlestickChart';
import type { PriceBar } from '../../api/tickerPrices';

const bars: PriceBar[] = Array.from({ length: 60 }, (_, i) => ({
  date: `2026-01-${String((i % 28) + 1).padStart(2, '0')}`,
  open: 100 + i,
  high: 102 + i,
  low: 98 + i,
  close: 101 + i,
  volume: 1_000_000 + i,
}));

describe('CandlestickChart', () => {
  beforeEach(() => {
    mocks.setDataCandle.mockClear();
    mocks.setDataVolume.mockClear();
    mocks.setDataLine.mockClear();
    mocks.applyOptions.mockClear();
    mocks.fitContent.mockClear();
    mocks.removeChart.mockClear();
  });

  it('renders the chart container and range selector', () => {
    render(
      <CandlestickChart bars={bars} range="6M" onRangeChange={() => {}} />,
    );
    expect(screen.getByTestId('candlestick-chart-container')).toBeInTheDocument();
    expect(screen.getByTestId('range-1M')).toBeInTheDocument();
    expect(screen.getByTestId('range-ALL')).toBeInTheDocument();
  });

  it('calls setData on the candle and volume series when bars arrive', () => {
    render(
      <CandlestickChart bars={bars} range="6M" onRangeChange={() => {}} />,
    );
    expect(mocks.setDataCandle).toHaveBeenCalledTimes(1);
    expect(mocks.setDataVolume).toHaveBeenCalledTimes(1);
    // MA50 + MA200 → setDataLine called for both lines.
    expect(mocks.setDataLine).toHaveBeenCalledTimes(2);
  });

  it('invokes onRangeChange when a range button is clicked', async () => {
    const user = userEvent.setup();
    const handler = vi.fn();
    render(<CandlestickChart bars={bars} range="6M" onRangeChange={handler} />);
    await user.click(screen.getByTestId('range-1Y'));
    expect(handler).toHaveBeenCalledWith('1Y');
  });

  it('renders the empty-state message with no bars', () => {
    render(<CandlestickChart bars={[]} range="6M" onRangeChange={() => {}} />);
    expect(screen.getByRole('status')).toHaveTextContent('價格資料準備中');
  });

  it('destroys the chart on unmount (no leak)', () => {
    const { unmount } = render(
      <CandlestickChart bars={bars} range="6M" onRangeChange={() => {}} />,
    );
    unmount();
    expect(mocks.removeChart).toHaveBeenCalledTimes(1);
    cleanup();
  });
});

describe('computeMovingAverage', () => {
  it('returns empty when fewer bars than window', () => {
    expect(computeMovingAverage(bars.slice(0, 10), 50)).toEqual([]);
  });

  it('averages the last N closes', () => {
    const ma = computeMovingAverage(bars, 5);
    // First entry is average of bars[0..4].close — 101,102,103,104,105 = 103.
    expect(ma[0]?.value).toBe(103);
  });
});
