import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { StalenessPill } from './StalenessPill';

describe('StalenessPill', () => {
  it('renders nothing when data_as_of is null', () => {
    const { container } = render(
      <StalenessPill dataAsOf={null} snapshotDate="2026-06-06" />,
    );
    expect(container.querySelector('[data-testid="staleness-pill"]')).toBeNull();
  });

  it('renders nothing when data_as_of is undefined', () => {
    const { container } = render(
      <StalenessPill dataAsOf={undefined} snapshotDate="2026-06-06" />,
    );
    expect(container.querySelector('[data-testid="staleness-pill"]')).toBeNull();
  });

  it('renders nothing when data_as_of equals snapshot date (fresh data)', () => {
    const { container } = render(
      <StalenessPill dataAsOf="2026-06-06" snapshotDate="2026-06-06" />,
    );
    expect(container.querySelector('[data-testid="staleness-pill"]')).toBeNull();
  });

  it('renders nothing when data_as_of is more recent than snapshot date', () => {
    // Pathological but defensive — shouldn't happen but the component
    // must not flag a "stale" warning for data that's actually newer.
    const { container } = render(
      <StalenessPill dataAsOf="2026-06-07" snapshotDate="2026-06-06" />,
    );
    expect(container.querySelector('[data-testid="staleness-pill"]')).toBeNull();
  });

  it('renders the pill with formatted month/day when data lags by 1 day', () => {
    render(<StalenessPill dataAsOf="2026-06-04" snapshotDate="2026-06-05" />);
    const pill = screen.getByTestId('staleness-pill');
    expect(pill.textContent).toContain('資料截至 6/4');
  });

  it('renders the pill with multi-day gap', () => {
    render(<StalenessPill dataAsOf="2026-05-29" snapshotDate="2026-06-05" />);
    const pill = screen.getByTestId('staleness-pill');
    expect(pill.textContent).toContain('資料截至 5/29');
  });

  it('attaches a descriptive aria-label that explains the gap', () => {
    render(<StalenessPill dataAsOf="2026-06-04" snapshotDate="2026-06-06" />);
    const pill = screen.getByTestId('staleness-pill');
    expect(pill.getAttribute('aria-label')).toContain('2026-06-04');
    expect(pill.getAttribute('aria-label')).toContain('2026-06-06');
    expect(pill.getAttribute('aria-label')).toContain('2 天');
  });

  it('renders nothing for malformed date strings (defensive)', () => {
    const { container } = render(
      <StalenessPill dataAsOf="not-a-date" snapshotDate="2026-06-06" />,
    );
    expect(container.querySelector('[data-testid="staleness-pill"]')).toBeNull();
  });
});
