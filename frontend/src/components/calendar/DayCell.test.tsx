import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { DayCell } from './DayCell';
import type { CalendarEvent } from '../../api/calendar';

function makeEvent(id: number, overrides: Partial<CalendarEvent> = {}): CalendarEvent {
  return {
    id,
    eventDate: new Date(2026, 5, 5),
    eventTime: null,
    type: 'earnings',
    tickerSymbol: `T${id}`,
    title: `Event ${id}`,
    payload: null,
    source: 'yfinance',
    ...overrides,
  };
}

describe('DayCell', () => {
  it('renders up to 3 inline chips and folds the rest behind +N', () => {
    const onOpen = vi.fn();
    render(
      <DayCell
        date={new Date(2026, 5, 5)}
        events={[makeEvent(1), makeEvent(2), makeEvent(3), makeEvent(4), makeEvent(5)]}
        inCurrentMonth
        isToday={false}
        isPast={false}
        onOpen={onOpen}
      />,
    );
    expect(screen.getAllByTestId('calendar-event-chip')).toHaveLength(3);
    expect(screen.getByTestId('calendar-day-overflow')).toHaveTextContent('+2');
  });

  it('does not render the overflow badge when ≤ 3 events', () => {
    render(
      <DayCell
        date={new Date(2026, 5, 5)}
        events={[makeEvent(1), makeEvent(2)]}
        inCurrentMonth
        isToday={false}
        isPast={false}
        onOpen={vi.fn()}
      />,
    );
    expect(screen.queryByTestId('calendar-day-overflow')).not.toBeInTheDocument();
  });

  it('marks today with the highlight chip and amber background', () => {
    render(
      <DayCell
        date={new Date(2026, 5, 5)}
        events={[]}
        inCurrentMonth
        isToday
        isPast={false}
        onOpen={vi.fn()}
      />,
    );
    const cell = screen.getByTestId('calendar-day-2026-6-5');
    expect(cell).toHaveAttribute('data-today', 'true');
    expect(cell.className).toMatch(/bg-amber/);
    expect(screen.getByText('今日')).toBeInTheDocument();
  });

  it('clicking the cell opens it via onOpen', async () => {
    const user = userEvent.setup();
    const onOpen = vi.fn();
    render(
      <DayCell
        date={new Date(2026, 5, 5)}
        events={[makeEvent(1)]}
        inCurrentMonth
        isToday={false}
        isPast={false}
        onOpen={onOpen}
      />,
    );
    await user.click(screen.getByTestId('calendar-day-2026-6-5'));
    expect(onOpen).toHaveBeenCalledTimes(1);
    expect(onOpen.mock.calls[0]?.[0]).toBeInstanceOf(Date);
  });

  it('greys out past events but still renders chips', () => {
    render(
      <DayCell
        date={new Date(2026, 4, 1)}
        events={[makeEvent(1), makeEvent(2)]}
        inCurrentMonth
        isToday={false}
        isPast
        onOpen={vi.fn()}
      />,
    );
    const chips = screen.getAllByTestId('calendar-event-chip');
    expect(chips).toHaveLength(2);
    for (const chip of chips) {
      expect(chip).toHaveAttribute('data-past', 'true');
    }
  });
});
