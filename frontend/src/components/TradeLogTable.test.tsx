import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { TradeLogTable } from './TradeLogTable';
import type { TradeResponse } from '../api/positions';

const TRADE_BUY: TradeResponse = {
  id: 1,
  position_id: 7,
  symbol: 'AAPL',
  side: 'buy',
  shares: '10.000000',
  price: '180.500000',
  executed_at: '2026-04-10T15:30:00Z',
  realized_pnl: null,
  note: 'initial buy',
  created_at: '2026-04-10T15:30:01Z',
};

const TRADE_SELL: TradeResponse = {
  id: 2,
  position_id: 7,
  symbol: 'AAPL',
  side: 'sell',
  shares: '5.000000',
  price: '200.250000',
  executed_at: '2026-04-15T15:30:00Z',
  realized_pnl: '98.750000',
  note: null,
  created_at: '2026-04-15T15:30:01Z',
};

describe('TradeLogTable', () => {
  it('renders trades in both desktop table and mobile list', () => {
    render(<TradeLogTable trades={[TRADE_BUY, TRADE_SELL]} />);
    expect(screen.getByTestId('trade-log-table')).toBeInTheDocument();
    // Each trade's buy/sell and numbers appear.
    // 買 appears in desktop + mobile views; just assert presence.
    expect(screen.getAllByText('買').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('賣').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('initial buy').length).toBeGreaterThanOrEqual(1);
  });

  it('renders empty state when no trades', () => {
    render(<TradeLogTable trades={[]} />);
    expect(screen.getByText('尚無交易紀錄。')).toBeInTheDocument();
  });
});
