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

  describe('industry trust modifiers', () => {
    const yesterdayIso = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();
    const longAgoIso = new Date(
      Date.now() - 30 * 24 * 60 * 60 * 1000,
    ).toISOString();

    it('renders a solid border for confirmed industry events', () => {
      render(
        <EventChip
          event={makeEvent({
            type: 'industry',
            tickerSymbol: null,
            title: 'Computex 2027',
            payload: {
              confidence: 'confirmed',
              last_verified_at: yesterdayIso,
              source_url: 'https://example.com',
            },
          })}
          past={false}
        />,
      );
      const chip = screen.getByTestId('calendar-event-chip');
      expect(chip).toHaveAttribute('data-confidence', 'confirmed');
      expect(chip.className).toMatch(/border-solid/);
    });

    it('renders a dashed border when the LLM marked the date estimated', () => {
      render(
        <EventChip
          event={makeEvent({
            type: 'industry',
            tickerSymbol: null,
            title: 'Computex 2027',
            payload: {
              confidence: 'estimated',
              last_verified_at: yesterdayIso,
            },
          })}
          past={false}
        />,
      );
      const chip = screen.getByTestId('calendar-event-chip');
      expect(chip).toHaveAttribute('data-confidence', 'estimated');
      expect(chip.className).toMatch(/border-dashed/);
    });

    it('renders a dotted border for uncertain industry events', () => {
      render(
        <EventChip
          event={makeEvent({
            type: 'industry',
            tickerSymbol: null,
            title: 'Computex 2027',
            payload: { confidence: 'uncertain', last_verified_at: yesterdayIso },
          })}
          past={false}
        />,
      );
      const chip = screen.getByTestId('calendar-event-chip');
      expect(chip).toHaveAttribute('data-confidence', 'uncertain');
      expect(chip.className).toMatch(/border-dotted/);
    });

    it('dims the chip when last_verified_at is older than the threshold', () => {
      render(
        <EventChip
          event={makeEvent({
            type: 'industry',
            tickerSymbol: null,
            title: 'Computex 2027',
            payload: {
              confidence: 'confirmed',
              last_verified_at: longAgoIso,
            },
          })}
          past={false}
          staleThresholdDays={21}
        />,
      );
      const chip = screen.getByTestId('calendar-event-chip');
      expect(chip).toHaveAttribute('data-stale', 'true');
      expect(chip.className).toMatch(/opacity-60/);
    });

    it('does not annotate yaml-sourced industry events that have no payload', () => {
      render(
        <EventChip
          event={makeEvent({
            type: 'industry',
            tickerSymbol: null,
            title: 'SpaceX IPO filing window',
            payload: { tags: ['Aerospace'] },
          })}
          past={false}
        />,
      );
      const chip = screen.getByTestId('calendar-event-chip');
      expect(chip).not.toHaveAttribute('data-confidence');
      expect(chip).not.toHaveAttribute('data-stale');
      expect(chip.className).toMatch(/border-solid/);
      expect(chip.className).not.toMatch(/opacity-60/);
    });
  });
});
