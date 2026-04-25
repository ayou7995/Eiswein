import { describe, it, expect } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { IndicatorCategoricalBars } from './IndicatorCategoricalBars';

const COLORS = {
  accum: '#22c55e',
  distrib: '#ef4444',
  neutral: '#64748b',
};

const LABELS = {
  accum: '進貨日',
  distrib: '出貨日',
  neutral: '中性',
};

describe('IndicatorCategoricalBars', () => {
  it('renders one rect per row using the colour map for each classification', () => {
    render(
      <IndicatorCategoricalBars
        series={[
          { date: '2026-04-20', classification: 'accum' },
          { date: '2026-04-21', classification: 'distrib' },
          { date: '2026-04-22', classification: 'neutral' },
          { date: '2026-04-23', classification: 'accum' },
        ]}
        colors={COLORS}
        legendLabels={LABELS}
        ariaLabel="A/D Day 25 日分類"
      />,
    );

    expect(screen.getByTestId('indicator-categorical-bars')).toBeInTheDocument();
    expect(screen.getAllByTestId('bar-accum')).toHaveLength(2);
    expect(screen.getAllByTestId('bar-distrib')).toHaveLength(1);
    expect(screen.getAllByTestId('bar-neutral')).toHaveLength(1);
    expect(screen.getByText('進貨日')).toBeInTheDocument();
    expect(screen.getByText('出貨日')).toBeInTheDocument();
    expect(screen.getByText('中性')).toBeInTheDocument();
  });

  it('shows empty placeholder when series is empty', () => {
    render(
      <IndicatorCategoricalBars
        series={[]}
        colors={COLORS}
        legendLabels={LABELS}
        ariaLabel="A/D Day 空資料"
      />,
    );
    expect(screen.getByTestId('indicator-categorical-bars-empty')).toBeInTheDocument();
  });

  it('reveals a tooltip with date + classification label on hover', () => {
    render(
      <IndicatorCategoricalBars
        series={[
          { date: '2026-04-20', classification: 'accum' },
          { date: '2026-04-21', classification: 'distrib' },
        ]}
        colors={COLORS}
        legendLabels={LABELS}
        ariaLabel="A/D Day"
      />,
    );

    const bars = screen.getAllByTestId('bar-accum');
    fireEvent.mouseEnter(bars[0]!);

    const tooltip = screen.getByTestId('indicator-categorical-tooltip');
    expect(tooltip).toHaveTextContent('2026-04-20');
    expect(tooltip).toHaveTextContent('進貨日');
  });
});
