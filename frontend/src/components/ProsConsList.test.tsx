import { describe, it, expect } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ProsConsList } from './ProsConsList';
import type { ProsConsItem } from '../api/prosCons';

const sampleItems: readonly ProsConsItem[] = [
  {
    category: 'direction',
    tone: 'pro',
    short_label: 'RSI 66，動能偏強',
    detail: { rsi: 66.2, threshold: 70 },
    indicator_name: 'rsi',
    timeframe: 'short',
  },
  {
    category: 'direction',
    tone: 'con',
    short_label: 'Volume 異常',
    detail: { volume_ratio: 2.4 },
    indicator_name: 'volume_anomaly',
    timeframe: 'short',
  },
  {
    category: 'timing',
    tone: 'neutral',
    short_label: '資料不足以判斷 MACD',
    detail: {},
    indicator_name: 'macd',
    timeframe: 'short',
  },
];

describe('ProsConsList', () => {
  it('renders the empty state message when items is empty', () => {
    render(<ProsConsList items={[]} />);
    expect(screen.getByRole('status')).toHaveTextContent('資料不足以判斷');
  });

  it('renders each non-neutral short_label verbatim', () => {
    render(<ProsConsList items={sampleItems} />);
    expect(screen.getByText('RSI 66，動能偏強')).toBeInTheDocument();
    expect(screen.getByText('Volume 異常')).toBeInTheDocument();
  });

  it('collapses neutrals under a summary group by default', () => {
    render(<ProsConsList items={sampleItems} />);
    expect(screen.getByTestId('neutral-summary')).toHaveTextContent('中性訊號 (1)');
  });

  it('expands a row to reveal the detail payload on click', async () => {
    const user = userEvent.setup();
    render(<ProsConsList items={sampleItems} />);
    const summaries = screen.getAllByTestId('pros-cons-summary');
    const first = summaries[0];
    expect(first).toBeDefined();
    const firstRow = (first as HTMLElement).closest('li');
    expect(firstRow).not.toBeNull();
    await user.click(first as HTMLElement);
    const termList = within(firstRow as HTMLElement);
    expect(termList.getByText('rsi')).toBeInTheDocument();
    expect(termList.getByText('66.2')).toBeInTheDocument();
  });

  it('does not emit the neutral group when collapseNeutrals is false', () => {
    render(<ProsConsList items={sampleItems} collapseNeutrals={false} />);
    expect(screen.queryByTestId('neutral-summary')).toBeNull();
    expect(screen.getByText(/資料不足以判斷 MACD/)).toBeInTheDocument();
  });

  it('renders a timeframe chip on each non-neutral row', () => {
    const items: readonly ProsConsItem[] = [
      {
        category: 'direction',
        tone: 'pro',
        short_label: 'RSI 短期訊號',
        detail: {},
        indicator_name: 'rsi',
        timeframe: 'short',
      },
      {
        category: 'macro',
        tone: 'con',
        short_label: '長期 USD 強勢',
        detail: {},
        indicator_name: 'dxy',
        timeframe: 'long',
      },
      {
        category: 'macro',
        tone: 'pro',
        short_label: 'SPX 中期多頭排列',
        detail: {},
        indicator_name: 'spx_ma',
        timeframe: 'mid',
      },
    ];
    render(<ProsConsList items={items} />);
    const chips = screen.getAllByTestId('timeframe-chip');
    expect(chips).toHaveLength(3);
    const labels = chips.map((c) => c.textContent);
    expect(labels).toContain('短期');
    expect(labels).toContain('中期');
    expect(labels).toContain('長期');
  });
});
