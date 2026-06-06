import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { RelatedIndicatorsRow } from './RelatedIndicatorsRow';
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

describe('RelatedIndicatorsRow', () => {
  it('shows aligned + opposite groups for a non-neutral indicator', () => {
    const items: ProsConsItem[] = [
      makeItem({ indicator_name: 'rsi', tone: 'pro', timeframe: 'short' }),
      makeItem({ indicator_name: 'macd', tone: 'pro', timeframe: 'short' }),
      makeItem({ indicator_name: 'bollinger', tone: 'pro', timeframe: 'short' }),
      makeItem({ indicator_name: 'volume_anomaly', tone: 'con', timeframe: 'short' }),
    ];
    render(
      <RelatedIndicatorsRow
        currentName="rsi"
        items={items}
        titleFor={(n) => n.toUpperCase()}
      />,
    );
    expect(screen.getByText('同方向 2:')).toBeTruthy();
    expect(screen.getByText('反方向 1:')).toBeTruthy();
    expect(screen.getByText('MACD')).toBeTruthy();
    expect(screen.getByText('BOLLINGER')).toBeTruthy();
    expect(screen.getByText('VOLUME_ANOMALY')).toBeTruthy();
  });

  it('excludes the current indicator from its own related lists', () => {
    const items: ProsConsItem[] = [
      makeItem({ indicator_name: 'rsi', tone: 'pro', timeframe: 'short' }),
      makeItem({ indicator_name: 'macd', tone: 'pro', timeframe: 'short' }),
    ];
    render(
      <RelatedIndicatorsRow
        currentName="rsi"
        items={items}
        titleFor={(n) => n}
      />,
    );
    expect(screen.queryByText('rsi')).toBeNull();
    expect(screen.getByText('macd')).toBeTruthy();
  });

  it('excludes cross-timeframe indicators from same-direction list', () => {
    const items: ProsConsItem[] = [
      makeItem({ indicator_name: 'rsi', tone: 'pro', timeframe: 'short' }),
      makeItem({ indicator_name: 'price_vs_ma', tone: 'pro', timeframe: 'mid' }),
      makeItem({ indicator_name: 'macd', tone: 'pro', timeframe: 'short' }),
    ];
    render(
      <RelatedIndicatorsRow
        currentName="rsi"
        items={items}
        titleFor={(n) => n}
      />,
    );
    expect(screen.getByText('同方向 1:')).toBeTruthy();
    expect(screen.queryByText('price_vs_ma')).toBeNull();
  });

  it('returns null when current indicator is neutral', () => {
    const items: ProsConsItem[] = [
      makeItem({ indicator_name: 'rsi', tone: 'neutral', timeframe: 'short' }),
      makeItem({ indicator_name: 'macd', tone: 'pro', timeframe: 'short' }),
    ];
    const { container } = render(
      <RelatedIndicatorsRow
        currentName="rsi"
        items={items}
        titleFor={(n) => n}
      />,
    );
    expect(container.querySelector('footer')).toBeNull();
  });

  it('returns null when there are no related indicators at all', () => {
    const items: ProsConsItem[] = [
      makeItem({ indicator_name: 'rsi', tone: 'pro', timeframe: 'short' }),
    ];
    const { container } = render(
      <RelatedIndicatorsRow
        currentName="rsi"
        items={items}
        titleFor={(n) => n}
      />,
    );
    expect(container.querySelector('footer')).toBeNull();
  });

  it('scrolls to the clicked sibling card', () => {
    const target = document.createElement('div');
    target.id = 'indicator-macd';
    const scrollIntoView = vi.fn();
    target.scrollIntoView = scrollIntoView;
    document.body.appendChild(target);

    const items: ProsConsItem[] = [
      makeItem({ indicator_name: 'rsi', tone: 'pro', timeframe: 'short' }),
      makeItem({ indicator_name: 'macd', tone: 'pro', timeframe: 'short' }),
    ];
    render(
      <RelatedIndicatorsRow
        currentName="rsi"
        items={items}
        titleFor={(n) => n.toUpperCase()}
      />,
    );
    fireEvent.click(screen.getByText('MACD'));
    expect(scrollIntoView).toHaveBeenCalledOnce();
    document.body.removeChild(target);
  });
});
