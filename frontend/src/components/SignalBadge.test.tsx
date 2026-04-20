import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { SignalBadge } from './SignalBadge';

describe('SignalBadge', () => {
  it('exposes the ARIA label for assistive tech', () => {
    render(<SignalBadge tone="green" ariaLabel="強力買入，評分 Green" />);
    expect(screen.getByRole('status')).toHaveAccessibleName('強力買入，評分 Green');
  });

  it('renders emoji + Chinese label + letter redundancy for green', () => {
    render(<SignalBadge tone="green" ariaLabel="買入" />);
    const badge = screen.getByTestId('signal-badge');
    expect(badge).toHaveTextContent('🟢');
    expect(badge).toHaveTextContent('買');
    expect(badge).toHaveTextContent('G');
    expect(badge).toHaveAttribute('data-tone', 'green');
  });

  it('renders redundant indicators for yellow', () => {
    render(<SignalBadge tone="yellow" ariaLabel="持有" />);
    const badge = screen.getByTestId('signal-badge');
    expect(badge).toHaveTextContent('🟡');
    expect(badge).toHaveTextContent('持');
    expect(badge).toHaveTextContent('Y');
  });

  it('renders redundant indicators for red', () => {
    render(<SignalBadge tone="red" ariaLabel="出場" />);
    const badge = screen.getByTestId('signal-badge');
    expect(badge).toHaveTextContent('🔴');
    expect(badge).toHaveTextContent('賣');
    expect(badge).toHaveTextContent('R');
  });

  it('renders redundant indicators for neutral (insufficient data)', () => {
    render(<SignalBadge tone="neutral" ariaLabel="資料不足" />);
    const badge = screen.getByTestId('signal-badge');
    expect(badge).toHaveTextContent('⚪');
    expect(badge).toHaveTextContent('N');
    expect(badge).toHaveAttribute('data-tone', 'neutral');
  });
});
