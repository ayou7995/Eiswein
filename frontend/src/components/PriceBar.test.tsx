import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { PriceBar } from './PriceBar';

describe('PriceBar', () => {
  it('renders both prices and a marker when data is present', () => {
    render(
      <PriceBar
        currentPrice={105.5}
        targetPrice={100}
        label="理想進場"
        toneAboveTarget="neutral"
        toneBelowTarget="green"
      />,
    );
    const bar = screen.getByTestId('price-bar');
    expect(bar).toHaveTextContent('105.50');
    expect(bar).toHaveTextContent('100.00');
    expect(screen.getByTestId('price-bar-marker')).toBeInTheDocument();
  });

  it('gracefully degrades when currentPrice is null', () => {
    render(
      <PriceBar currentPrice={null} targetPrice={100} label="停損" />,
    );
    const bar = screen.getByTestId('price-bar');
    expect(bar).toHaveTextContent('—');
    expect(bar).toHaveTextContent('100.00');
    expect(screen.queryByTestId('price-bar-marker')).toBeNull();
  });

  it('gracefully degrades when targetPrice is null', () => {
    render(
      <PriceBar currentPrice={100} targetPrice={null} label="停損" />,
    );
    const bar = screen.getByTestId('price-bar');
    expect(bar).toHaveTextContent('100.00');
    expect(bar).toHaveTextContent('—');
  });

  it('exposes an ARIA label that includes the numeric context', () => {
    render(
      <PriceBar currentPrice={105} targetPrice={100} label="理想進場" />,
    );
    expect(screen.getByRole('group')).toHaveAccessibleName(
      '理想進場：目前 105.00，目標 100.00',
    );
  });

  it('falls back to an insufficient-data ARIA label when prices missing', () => {
    render(<PriceBar currentPrice={null} targetPrice={null} label="停損" />);
    expect(screen.getByRole('group')).toHaveAccessibleName('停損：資料不足');
  });

  it('accepts an explicit ariaLabel override', () => {
    render(
      <PriceBar
        currentPrice={50}
        targetPrice={100}
        label="停損"
        ariaLabel="自訂描述"
      />,
    );
    expect(screen.getByRole('group')).toHaveAccessibleName('自訂描述');
  });
});
