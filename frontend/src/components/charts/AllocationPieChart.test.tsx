import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { AllocationPieChart } from './AllocationPieChart';

describe('AllocationPieChart', () => {
  it('renders a donut + legend with multiple slices', () => {
    render(
      <AllocationPieChart
        slices={[
          { label: 'AAPL', value: 1000 },
          { label: 'MSFT', value: 500 },
        ]}
      />,
    );
    // SVG chart is present and labelled.
    const svg = screen.getByRole('img');
    expect(svg).toHaveAttribute('aria-label', expect.stringContaining('AAPL'));
    expect(svg).toHaveAttribute('aria-label', expect.stringContaining('MSFT'));
    const legend = screen.getByTestId('allocation-legend');
    expect(legend).toBeInTheDocument();
    expect(legend).toHaveTextContent('AAPL');
    expect(legend).toHaveTextContent('MSFT');
  });

  it('renders empty state when no slices are provided', () => {
    render(<AllocationPieChart slices={[]} />);
    expect(screen.getByTestId('allocation-empty')).toHaveTextContent('尚未建立持倉');
  });

  it('handles a single full-donut slice', () => {
    render(<AllocationPieChart slices={[{ label: 'AAPL', value: 100 }]} />);
    expect(screen.getByTestId('allocation-pie')).toBeInTheDocument();
    expect(screen.getByRole('img')).toHaveAttribute(
      'aria-label',
      expect.stringContaining('AAPL 100.0%'),
    );
  });

  it('ignores zero/negative value slices', () => {
    render(
      <AllocationPieChart
        slices={[
          { label: 'AAPL', value: 100 },
          { label: 'ZERO', value: 0 },
          { label: 'NEG', value: -5 },
        ]}
      />,
    );
    const legend = screen.getByTestId('allocation-legend');
    expect(legend).toHaveTextContent('AAPL');
    expect(legend).not.toHaveTextContent('ZERO');
    expect(legend).not.toHaveTextContent('NEG');
  });
});
