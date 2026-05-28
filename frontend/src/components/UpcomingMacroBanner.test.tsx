import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { screen, within } from '@testing-library/react';
import { UpcomingMacroBanner } from './UpcomingMacroBanner';
import { renderWithProviders } from '../test/utils';
import type { CalendarEventListResult } from '../api/calendar';

vi.mock('../hooks/useCalendar', () => ({
  useCalendarEvents: vi.fn(),
}));

import { useCalendarEvents } from '../hooks/useCalendar';

const mockUse = vi.mocked(useCalendarEvents);

function prime(result: Partial<CalendarEventListResult>, isLoading = false): void {
  mockUse.mockReturnValue({
    data: {
      data: result.data ?? [],
      total: result.total ?? 0,
      rangeStart: result.rangeStart ?? new Date(),
      rangeEnd: result.rangeEnd ?? new Date(),
    },
    isLoading,
    isError: false,
    error: null,
    refetch: vi.fn(),
  } as unknown as ReturnType<typeof useCalendarEvents>);
}

beforeEach(() => {
  prime({ data: [] });
});

afterEach(() => {
  vi.clearAllMocks();
});

describe('UpcomingMacroBanner', () => {
  it('renders nothing when no upcoming macro events', () => {
    prime({ data: [] });
    const { container } = renderWithProviders(<UpcomingMacroBanner />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders nothing while the query is loading (no flicker)', () => {
    prime({ data: [] }, true);
    const { container } = renderWithProviders(<UpcomingMacroBanner />);
    expect(container).toBeEmptyDOMElement();
  });

  it('lists each upcoming macro event with weekday + optional time', () => {
    prime({
      data: [
        {
          id: 1,
          eventDate: new Date(2026, 5, 8), // Mon
          eventTime: '8:30 ET',
          type: 'macro',
          tickerSymbol: null,
          title: 'CPI Release',
          payload: null,
          source: 'hardcoded',
        },
        {
          id: 2,
          eventDate: new Date(2026, 5, 10), // Wed
          eventTime: '14:00 ET',
          type: 'macro',
          tickerSymbol: null,
          title: 'FOMC Meeting',
          payload: null,
          source: 'hardcoded',
        },
      ],
    });
    renderWithProviders(<UpcomingMacroBanner />);
    const banner = screen.getByTestId('upcoming-macro-banner');
    expect(within(banner).getByText(/CPI/)).toBeInTheDocument();
    expect(within(banner).getByText(/FOMC/)).toBeInTheDocument();
    // Strip the "Release" suffix.
    expect(within(banner).queryByText(/CPI Release/)).not.toBeInTheDocument();
  });

  it('links each event to the calendar with ?date= preselected', () => {
    prime({
      data: [
        {
          id: 1,
          eventDate: new Date(2026, 5, 8),
          eventTime: null,
          type: 'macro',
          tickerSymbol: null,
          title: 'NFP',
          payload: null,
          source: 'hardcoded',
        },
      ],
    });
    renderWithProviders(<UpcomingMacroBanner />);
    const link = screen.getByRole('link');
    expect(link.getAttribute('href')).toBe('/calendar?date=2026-06-08');
  });
});
