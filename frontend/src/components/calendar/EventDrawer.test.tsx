import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { EventDrawer } from './EventDrawer';
import type { CalendarEvent } from '../../api/calendar';

function makeEvent(overrides: Partial<CalendarEvent> = {}): CalendarEvent {
  return {
    id: 1,
    eventDate: new Date(2026, 5, 5),
    eventTime: 'AMC',
    type: 'earnings',
    tickerSymbol: 'AAPL',
    title: 'AAPL Earnings',
    payload: { time_marker: 'AMC', consensus_eps: 1.42 },
    source: 'yfinance',
    ...overrides,
  };
}

describe('EventDrawer', () => {
  it('renders the date header and each event row', () => {
    render(
      <EventDrawer
        date={new Date(2026, 5, 5)}
        events={[
          makeEvent({ id: 1 }),
          makeEvent({ id: 2, type: 'macro', tickerSymbol: null, title: 'CPI Release', eventTime: '8:30 ET' }),
        ]}
        isPast={false}
        onClose={vi.fn()}
        onNavigateDay={vi.fn()}
      />,
    );
    expect(screen.getByTestId('calendar-event-drawer')).toBeInTheDocument();
    expect(screen.getByTestId('calendar-event-detail-1')).toBeInTheDocument();
    expect(screen.getByTestId('calendar-event-detail-2')).toBeInTheDocument();
    expect(screen.getByText(/2026\/6\/5/)).toBeInTheDocument();
  });

  it('renders an empty-state when there are zero events', () => {
    render(
      <EventDrawer
        date={new Date(2026, 5, 5)}
        events={[]}
        isPast={false}
        onClose={vi.fn()}
        onNavigateDay={vi.fn()}
      />,
    );
    expect(screen.getByText('今日無事件')).toBeInTheDocument();
  });

  it('closes on ESC', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(
      <EventDrawer
        date={new Date(2026, 5, 5)}
        events={[makeEvent()]}
        isPast={false}
        onClose={onClose}
        onNavigateDay={vi.fn()}
      />,
    );
    await user.keyboard('{Escape}');
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('closes when the backdrop is clicked', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(
      <EventDrawer
        date={new Date(2026, 5, 5)}
        events={[makeEvent()]}
        isPast={false}
        onClose={onClose}
        onNavigateDay={vi.fn()}
      />,
    );
    await user.click(screen.getByTestId('calendar-event-drawer-backdrop'));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('arrow keys + footer buttons trigger day navigation', async () => {
    const user = userEvent.setup();
    const onNavigateDay = vi.fn();
    render(
      <EventDrawer
        date={new Date(2026, 5, 5)}
        events={[makeEvent()]}
        isPast={false}
        onClose={vi.fn()}
        onNavigateDay={onNavigateDay}
      />,
    );
    await user.keyboard('{ArrowRight}');
    expect(onNavigateDay).toHaveBeenLastCalledWith(1);
    await user.keyboard('{ArrowLeft}');
    expect(onNavigateDay).toHaveBeenLastCalledWith(-1);
    await user.click(screen.getByRole('button', { name: /次日/ }));
    expect(onNavigateDay).toHaveBeenLastCalledWith(1);
    await user.click(screen.getByRole('button', { name: /前一日/ }));
    expect(onNavigateDay).toHaveBeenLastCalledWith(-1);
  });

  it('surfaces consensus EPS and time marker from payload', () => {
    render(
      <EventDrawer
        date={new Date(2026, 5, 5)}
        events={[makeEvent()]}
        isPast={false}
        onClose={vi.fn()}
        onNavigateDay={vi.fn()}
      />,
    );
    expect(screen.getByText(/共識 EPS: \$1\.42/)).toBeInTheDocument();
    expect(screen.getByText(/時間: AMC/)).toBeInTheDocument();
  });
});
