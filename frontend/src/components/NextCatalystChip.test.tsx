import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { screen } from '@testing-library/react';
import { NextCatalystChip } from './NextCatalystChip';
import { renderWithProviders } from '../test/utils';
import type { CalendarEvent } from '../api/calendar';

vi.mock('../hooks/useCalendar', () => ({
  useCalendarEvents: vi.fn(),
}));

import { useCalendarEvents } from '../hooks/useCalendar';

const mockUse = vi.mocked(useCalendarEvents);

function event(overrides: Partial<CalendarEvent>): CalendarEvent {
  return {
    id: 1,
    eventDate: new Date(),
    eventTime: null,
    type: 'earnings',
    tickerSymbol: 'NVDA',
    title: 'NVDA Earnings',
    payload: null,
    source: 'yfinance',
    ...overrides,
  };
}

function prime(events: CalendarEvent[], isLoading = false): void {
  mockUse.mockReturnValue({
    data: {
      data: events,
      total: events.length,
      rangeStart: new Date(),
      rangeEnd: new Date(),
    },
    isLoading,
    isError: false,
    error: null,
    refetch: vi.fn(),
  } as unknown as ReturnType<typeof useCalendarEvents>);
}

beforeEach(() => {
  prime([]);
});

afterEach(() => {
  vi.clearAllMocks();
});

describe('NextCatalystChip', () => {
  it('renders nothing when the ticker has no upcoming catalyst', () => {
    prime([]);
    const { container } = renderWithProviders(<NextCatalystChip symbol="NVDA" />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders nothing while the query is loading', () => {
    prime([], true);
    const { container } = renderWithProviders(<NextCatalystChip symbol="NVDA" />);
    expect(container).toBeEmptyDOMElement();
  });

  it('shows the days-until + type + time marker for the earliest upcoming event', () => {
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const target = new Date(today);
    target.setDate(target.getDate() + 4);
    prime([
      event({
        id: 1,
        eventDate: target,
        eventTime: 'AMC',
        tickerSymbol: 'NVDA',
        title: 'NVDA Earnings',
      }),
    ]);
    renderWithProviders(<NextCatalystChip symbol="NVDA" />);
    const chip = screen.getByTestId('next-catalyst-chip');
    expect(chip).toHaveTextContent('4d');
    expect(chip).toHaveTextContent('財報 AMC');
  });

  it('renders "今日" when the event is today', () => {
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    prime([event({ eventDate: today, tickerSymbol: 'NVDA' })]);
    renderWithProviders(<NextCatalystChip symbol="NVDA" />);
    expect(screen.getByTestId('next-catalyst-chip')).toHaveTextContent('今日');
  });

  it('skips macro events that came back via the ticker filter', () => {
    // Backend always returns macro events alongside ticker matches —
    // the chip must NOT promote a macro event as the ticker's catalyst.
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const target = new Date(today);
    target.setDate(target.getDate() + 2);
    prime([
      event({
        id: 99,
        eventDate: target,
        type: 'macro',
        tickerSymbol: null,
        title: 'CPI Release',
      }),
    ]);
    const { container } = renderWithProviders(<NextCatalystChip symbol="NVDA" />);
    expect(container).toBeEmptyDOMElement();
  });

  it('links to the calendar page with the catalyst date preselected', () => {
    const target = new Date(2026, 5, 18);
    prime([event({ eventDate: target, tickerSymbol: 'AAPL' })]);
    renderWithProviders(<NextCatalystChip symbol="AAPL" />);
    const link = screen.getByRole('link');
    expect(link.getAttribute('href')).toBe('/calendar?date=2026-06-18');
  });
});
