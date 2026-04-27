import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, cleanup } from '@testing-library/react';

const mocks = vi.hoisted(() => {
  const setDataCandle = vi.fn();
  const setDataVolume = vi.fn();
  const setDataAdStrip = vi.fn();
  const fitContent = vi.fn();
  return { setDataCandle, setDataVolume, setDataAdStrip, fitContent };
});

vi.mock('lightweight-charts', () => {
  const candleSeries = { setData: mocks.setDataCandle, applyOptions: vi.fn() };
  // Two histogram series (volume + ad-strip) — return them in call order.
  let histogramCalls = 0;
  const histogramSeries = [
    { setData: mocks.setDataVolume, applyOptions: vi.fn() },
    { setData: mocks.setDataAdStrip, applyOptions: vi.fn() },
  ];
  const chart = {
    addCandlestickSeries: vi.fn(() => candleSeries),
    addHistogramSeries: vi.fn(() => histogramSeries[histogramCalls++ % 2]),
    priceScale: vi.fn(() => ({ applyOptions: vi.fn() })),
    timeScale: vi.fn(() => ({ fitContent: mocks.fitContent })),
    applyOptions: vi.fn(),
    remove: vi.fn(),
  };
  return {
    createChart: vi.fn(() => chart),
    ColorType: { Solid: 'solid' },
  };
});

import { AdDayCandleClassificationChart } from './AdDayCandleClassificationChart';
import type { AdDaySeriesResponse } from '../../api/marketIndicatorSeries';

const sampleResponse: AdDaySeriesResponse = {
  indicator: 'ad_day',
  series: Array.from({ length: 30 }, (_, i) => ({
    date: `2026-04-${String((i % 30) + 1).padStart(2, '0')}`,
    classification: (i % 3 === 0 ? 'accum' : i % 3 === 1 ? 'distrib' : 'neutral') as
      | 'accum'
      | 'distrib'
      | 'neutral',
    spx_change: 0.1 * i,
    volume_ratio: 1 + i * 0.01,
    open: 700 + i,
    high: 705 + i,
    low: 695 + i,
    close: 702 + i,
    volume: 50000000 + i * 100000,
  })),
  summary_zh: 'test',
  current: {
    accum_count_25d: 10,
    distrib_count_25d: 10,
    net_25d: 0,
    accum_count_5d: 2,
    distrib_count_5d: 2,
    net_5d: 0,
  },
};

describe('AdDayCandleClassificationChart', () => {
  beforeEach(() => {
    mocks.setDataCandle.mockClear();
    mocks.setDataVolume.mockClear();
    mocks.setDataAdStrip.mockClear();
    mocks.fitContent.mockClear();
    cleanup();
  });

  it('feeds candle, volume, and A/D strip data to lightweight-charts', () => {
    render(<AdDayCandleClassificationChart response={sampleResponse} />);

    const candleData = mocks.setDataCandle.mock.calls.at(-1)?.[0];
    expect(candleData.length).toBe(30);
    expect(candleData[0].open).toBe(700);
    // Standard up/down coloring is now handled at the series level —
    // candles no longer carry per-bar color overrides.
    expect(candleData[0].color).toBeUndefined();

    const volumeData = mocks.setDataVolume.mock.calls.at(-1)?.[0];
    expect(volumeData.length).toBe(30);
    expect(volumeData[0].value).toBe(50000000);
    // Volume color tracks candle direction (close vs open), not A/D class.
    expect(volumeData[0].color).toContain('22c55e'); // close > open here

    const adData = mocks.setDataAdStrip.mock.calls.at(-1)?.[0];
    expect(adData.length).toBe(30);
    // Strip uses a constant value per bar — only color encodes meaning.
    expect(adData[0].value).toBe(1);
    // First row classification is 'accum' → green hex.
    expect(adData[0].color).toBe('#22c55e');
  });
});
