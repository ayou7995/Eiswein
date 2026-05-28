import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { EventTypeFilter } from './EventTypeFilter';
import type { EventType } from '../../api/calendar';

describe('EventTypeFilter', () => {
  it('marks "全部" as active when no type is selected', () => {
    render(<EventTypeFilter selected={new Set()} onChange={vi.fn()} />);
    expect(screen.getByRole('button', { name: '全部' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
  });

  it('toggling a type adds it to the selection set', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn<(next: ReadonlySet<EventType>) => void>();
    render(<EventTypeFilter selected={new Set()} onChange={onChange} />);
    await user.click(screen.getByRole('button', { name: '財報' }));
    const passed = onChange.mock.calls[0]?.[0];
    expect(passed).toBeInstanceOf(Set);
    expect(Array.from(passed ?? new Set())).toEqual(['earnings']);
  });

  it('clicking "全部" resets the selection set', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn<(next: ReadonlySet<EventType>) => void>();
    render(<EventTypeFilter selected={new Set(['earnings', 'macro'])} onChange={onChange} />);
    await user.click(screen.getByRole('button', { name: '全部' }));
    const passed = onChange.mock.calls[0]?.[0];
    expect(passed).toBeInstanceOf(Set);
    expect((passed as ReadonlySet<EventType>).size).toBe(0);
  });

  it('selected type chip shows its colored tint', () => {
    render(
      <EventTypeFilter selected={new Set(['industry'])} onChange={vi.fn()} />,
    );
    const industryBtn = screen.getByRole('button', { name: '產業' });
    expect(industryBtn).toHaveAttribute('aria-pressed', 'true');
    expect(industryBtn.className).toMatch(/violet/);
  });
});
