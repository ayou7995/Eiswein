import { describe, it, expect } from 'vitest';
import { computeYBounds } from './yAxisAutoFit';

describe('computeYBounds', () => {
  it('falls back to soft bounds on empty series', () => {
    const bounds = computeYBounds([], ['adx'], { softMin: 0, softMax: 100 });
    expect(bounds.yMin).toBe(0);
    expect(bounds.yMax).toBe(100);
  });

  it('uses safe defaults when no soft bounds AND empty series', () => {
    const bounds = computeYBounds([], ['x']);
    expect(bounds.yMin).toBe(0);
    expect(bounds.yMax).toBe(1);
    expect(bounds.yMax).toBeGreaterThan(bounds.yMin);
  });

  it('respects softMin floor when percentile would go below it', () => {
    // All values 40-60 — 2% percentile would be near 40-something but
    // softMin=0 forces a non-negative floor regardless.
    const series = Array.from({ length: 30 }, (_, i) => ({ rsi: 40 + i }));
    const bounds = computeYBounds(series, ['rsi'], { softMin: 0, softMax: 100 });
    expect(bounds.yMin).toBeGreaterThanOrEqual(0);
    expect(bounds.yMax).toBeLessThanOrEqual(100);
    // Should be much tighter than 0-100 — actual data fits 40-69.
    expect(bounds.yMax - bounds.yMin).toBeLessThan(50);
  });

  it('caps at softMax even when data approaches it', () => {
    const series = Array.from({ length: 30 }, (_, i) => ({ x: 95 + i * 0.5 }));
    const bounds = computeYBounds(series, ['x'], { softMin: 0, softMax: 100 });
    expect(bounds.yMax).toBeLessThanOrEqual(100);
  });

  it('clips a single outlier using the 98th percentile', () => {
    // 100 normal bars in 10-20, one freak spike at 200. Percentile clip
    // should ignore the spike and keep the upper bound near 20-ish.
    const series: Array<{ x: number }> = Array.from({ length: 100 }, () => ({ x: 15 }));
    series[50] = { x: 200 };
    const bounds = computeYBounds(series, ['x'], { softMin: 0 });
    expect(bounds.yMax).toBeLessThan(50);
  });

  it('skips null values in the series', () => {
    const series = [
      { adx: null as number | null },
      { adx: 20 },
      { adx: 30 },
      { adx: 40 },
    ];
    const bounds = computeYBounds(series as Array<{ adx: number | null }>, ['adx'], {
      softMin: 0,
    });
    expect(bounds.yMin).toBeGreaterThanOrEqual(0);
    expect(bounds.yMax).toBeGreaterThan(bounds.yMin);
  });

  it('handles multiple keys for multi-line charts', () => {
    // ADX chart has adx + plus_di + minus_di — auto-fit must consider all.
    const series = [
      { adx: 25, plus_di: 30, minus_di: 15 },
      { adx: 30, plus_di: 35, minus_di: 18 },
      { adx: 40, plus_di: 42, minus_di: 20 },
    ];
    const bounds = computeYBounds(series, ['adx', 'plus_di', 'minus_di'], {
      softMin: 0,
    });
    expect(bounds.yMax).toBeGreaterThanOrEqual(42);
    expect(bounds.yMin).toBeLessThanOrEqual(15);
  });

  it('guarantees a non-zero span even on degenerate constant series', () => {
    const series = Array.from({ length: 30 }, () => ({ x: 5 }));
    const bounds = computeYBounds(series, ['x']);
    expect(bounds.yMax).toBeGreaterThan(bounds.yMin);
  });
});
