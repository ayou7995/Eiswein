import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { IndicatorIndexBar } from './IndicatorIndexBar';
import type { ProsConsItem } from '../api/prosCons';

function makeItem(overrides: Partial<ProsConsItem>): ProsConsItem {
  return {
    category: 'direction',
    tone: 'pro',
    short_label: '',
    detail: {},
    indicator_name: 'rsi',
    timeframe: 'short',
    ...overrides,
  };
}

describe('IndicatorIndexBar', () => {
  it('groups items into short/mid/long rows in that order', () => {
    const items: ProsConsItem[] = [
      makeItem({ indicator_name: 'dxy', timeframe: 'long', tone: 'neutral' }),
      makeItem({ indicator_name: 'rsi', timeframe: 'short', tone: 'pro' }),
      makeItem({ indicator_name: 'adx', timeframe: 'mid', tone: 'con' }),
    ];
    render(<IndicatorIndexBar items={items} titleFor={(n) => n.toUpperCase()} />);
    const labels = screen.getAllByText(/短期|中期|長期/);
    // Order must be short → mid → long irrespective of input order.
    expect(labels[0].textContent).toBe('短期');
    expect(labels[1].textContent).toBe('中期');
    expect(labels[2].textContent).toBe('長期');
  });

  it('omits a row when no items match that timeframe', () => {
    const items: ProsConsItem[] = [
      makeItem({ indicator_name: 'rsi', timeframe: 'short' }),
    ];
    render(<IndicatorIndexBar items={items} titleFor={(n) => n.toUpperCase()} />);
    expect(screen.queryByText('中期')).toBeNull();
    expect(screen.queryByText('長期')).toBeNull();
    expect(screen.getByText('短期')).toBeTruthy();
  });

  it('renders a chip per item with the resolved title', () => {
    const items: ProsConsItem[] = [
      makeItem({ indicator_name: 'rsi', timeframe: 'short' }),
      makeItem({ indicator_name: 'macd', timeframe: 'short' }),
    ];
    render(
      <IndicatorIndexBar
        items={items}
        titleFor={(n) => (n === 'rsi' ? 'RSI' : 'MACD')}
      />,
    );
    expect(screen.getByRole('button', { name: /跳到 RSI/ })).toBeTruthy();
    expect(screen.getByRole('button', { name: /跳到 MACD/ })).toBeTruthy();
  });

  it('triggers scrollIntoView on the matching anchor when clicked', () => {
    const anchor = document.createElement('div');
    anchor.id = 'indicator-rsi';
    const scrollIntoView = vi.fn();
    anchor.scrollIntoView = scrollIntoView;
    document.body.appendChild(anchor);

    const items: ProsConsItem[] = [
      makeItem({ indicator_name: 'rsi', timeframe: 'short' }),
    ];
    render(<IndicatorIndexBar items={items} titleFor={() => 'RSI'} />);
    fireEvent.click(screen.getByRole('button', { name: /跳到 RSI/ }));
    expect(scrollIntoView).toHaveBeenCalledOnce();
    document.body.removeChild(anchor);
  });

  it('uses a custom idFor when supplied', () => {
    const anchor = document.createElement('div');
    anchor.id = 'regime-vix';
    const scrollIntoView = vi.fn();
    anchor.scrollIntoView = scrollIntoView;
    document.body.appendChild(anchor);

    const items: ProsConsItem[] = [
      makeItem({ indicator_name: 'vix', timeframe: 'short' }),
    ];
    render(
      <IndicatorIndexBar
        items={items}
        titleFor={() => 'VIX'}
        idFor={(n) => `regime-${n}`}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: /跳到 VIX/ }));
    expect(scrollIntoView).toHaveBeenCalledOnce();
    document.body.removeChild(anchor);
  });

  it('renders nothing when items is empty', () => {
    const { container } = render(
      <IndicatorIndexBar items={[]} titleFor={() => ''} />,
    );
    expect(container.querySelector('nav')).toBeNull();
  });
});
