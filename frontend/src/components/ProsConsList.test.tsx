import { describe, it, expect } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ProsConsList } from './ProsConsList';
import type { ProsConsItem } from '../api/prosCons';

const sampleItems: readonly ProsConsItem[] = [
  {
    category: 'direction',
    tone: 'green',
    short_label: 'RSI 66，動能偏強',
    detail: { rsi: 66.2, threshold: 70 },
    indicator_name: 'rsi',
  },
  {
    category: 'direction',
    tone: 'red',
    short_label: 'Volume 異常',
    detail: { volume_ratio: 2.4 },
    indicator_name: 'volume_anomaly',
  },
  {
    category: 'timing',
    tone: 'neutral',
    short_label: '資料不足以判斷 MACD',
    detail: {},
    indicator_name: 'macd',
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
});
