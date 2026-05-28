import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { EventChip } from './EventChip';
import type { CalendarEvent } from '../../api/calendar';

function makeEvent(overrides: Partial<CalendarEvent>): CalendarEvent {
  return {
    id: 1,
    eventDate: new Date(2026, 5, 5),
    eventTime: null,
    type: 'earnings',
    tickerSymbol: 'AAPL',
    title: 'AAPL Earnings',
    payload: null,
    source: 'yfinance',
    ...overrides,
  };
}

describe('EventChip', () => {
  it('renders the ticker symbol for earnings events', () => {
    render(<EventChip event={makeEvent({ tickerSymbol: 'NVDA' })} past={false} />);
    const chip = screen.getByTestId('calendar-event-chip');
    expect(chip).toHaveTextContent('NVDA');
    expect(chip).toHaveAttribute('data-event-type', 'earnings');
  });

  it('appends the time marker for earnings (BMO/AMC)', () => {
    render(
      <EventChip
        event={makeEvent({ tickerSymbol: 'MSFT', eventTime: 'AMC' })}
        past={false}
      />,
    );
    expect(screen.getByTestId('calendar-event-chip')).toHaveTextContent('MSFT AMC');
  });

  it('trims the "Release" suffix from macro titles', () => {
    render(
      <EventChip
        event={makeEvent({
          type: 'macro',
          tickerSymbol: null,
          title: 'CPI Release',
        })}
        past={false}
      />,
    );
    expect(screen.getByTestId('calendar-event-chip')).toHaveTextContent('CPI');
  });

  it('uses the violet palette for industry events', () => {
    render(
      <EventChip
        event={makeEvent({
          type: 'industry',
          tickerSymbol: 'NVDA',
          title: 'NVDA GTC Day 1',
        })}
        past={false}
      />,
    );
    const chip = screen.getByTestId('calendar-event-chip');
    expect(chip).toHaveAttribute('data-event-type', 'industry');
    expect(chip.className).toMatch(/violet/);
  });

  it('greys out past events regardless of type', () => {
    render(<EventChip event={makeEvent({})} past />);
    const chip = screen.getByTestId('calendar-event-chip');
    expect(chip).toHaveAttribute('data-past', 'true');
    expect(chip.className).not.toMatch(/emerald/);
    expect(chip.className).toMatch(/stone/);
  });
});
