import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { DataFreshnessBadge } from './DataFreshnessBadge';
import type { DataFreshness } from '../api/settings';

function freshness(over: Partial<DataFreshness> = {}): DataFreshness {
  return {
    session_date: '2026-04-14',
    is_trading_day_today: true,
    market_close_at: '2026-04-14T16:00:00-04:00',
    latest_updated_at: '2026-04-14T20:00:00+00:00',
    is_intraday_partial: false,
    ...over,
  };
}

describe('DataFreshnessBadge', () => {
  it('renders 已收盤 when today is a settled trading day', () => {
    render(<DataFreshnessBadge freshness={freshness()} />);
    const badge = screen.getByTestId('data-freshness-badge');
    expect(badge).toHaveTextContent('已收盤');
    expect(badge).toHaveTextContent('16:00 ET');
  });

  it('renders 盤中即時 when the row is pre-close', () => {
    render(
      <DataFreshnessBadge
        freshness={freshness({ is_intraday_partial: true })}
      />,
    );
    const badge = screen.getByTestId('data-freshness-badge');
    expect(badge).toHaveTextContent('盤中即時');
    // Tooltip text references unfinalized close.
    expect(badge.getAttribute('aria-label')).toMatch(/尚未收盤/);
  });

  it('renders 休市 on a non-trading day', () => {
    render(
      <DataFreshnessBadge
        freshness={freshness({
          is_trading_day_today: false,
          market_close_at: null,
          is_intraday_partial: false,
        })}
      />,
    );
    expect(screen.getByTestId('data-freshness-badge')).toHaveTextContent(
      '休市',
    );
  });
});
