import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { PositionForm } from './PositionForm';

describe('PositionForm', () => {
  it('renders a symbol dropdown in open mode and rejects an empty symbol', async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(
      <PositionForm
        mode="open"
        availableSymbols={['AAPL', 'MSFT']}
        onSubmit={onSubmit}
        onCancel={() => {}}
      />,
    );
    await user.type(screen.getByLabelText('股數'), '10');
    await user.type(screen.getByLabelText('單價'), '100');
    await user.click(screen.getByRole('button', { name: /建立持倉/ }));
    await waitFor(() => {
      expect(screen.getByText('請選擇股票代碼')).toBeInTheDocument();
    });
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('rejects non-positive shares', async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(
      <PositionForm
        mode="open"
        availableSymbols={['AAPL']}
        onSubmit={onSubmit}
        onCancel={() => {}}
      />,
    );
    await user.selectOptions(screen.getByLabelText('股票代碼'), 'AAPL');
    await user.type(screen.getByLabelText('股數'), '-1');
    await user.type(screen.getByLabelText('單價'), '100');
    await user.click(screen.getByRole('button', { name: /建立持倉/ }));
    await waitFor(() => {
      expect(screen.getByText('請輸入正數')).toBeInTheDocument();
    });
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('enforces maxShares cap in reduce mode', async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(
      <PositionForm
        mode="reduce"
        symbol="AAPL"
        maxShares="5"
        onSubmit={onSubmit}
        onCancel={() => {}}
      />,
    );
    await user.type(screen.getByLabelText(/股數/), '10');
    await user.type(screen.getByLabelText('單價'), '100');
    await user.click(screen.getByRole('button', { name: /減碼/ }));
    await waitFor(() => {
      expect(screen.getByText(/減碼股數不可超過 5/)).toBeInTheDocument();
    });
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('submits valid values in add mode', async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(
      <PositionForm
        mode="add"
        symbol="AAPL"
        onSubmit={onSubmit}
        onCancel={() => {}}
      />,
    );
    await user.type(screen.getByLabelText('股數'), '3');
    await user.type(screen.getByLabelText('單價'), '185');
    await user.click(screen.getByRole('button', { name: /加碼/ }));
    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledTimes(1);
    });
    const values = onSubmit.mock.calls[0]?.[0];
    expect(values?.shares).toBe('3');
    expect(values?.price).toBe('185');
  });

  it('cancel button fires onCancel', async () => {
    const user = userEvent.setup();
    const onCancel = vi.fn();
    render(
      <PositionForm
        mode="open"
        availableSymbols={['AAPL']}
        onSubmit={vi.fn()}
        onCancel={onCancel}
      />,
    );
    await user.click(screen.getByRole('button', { name: '取消' }));
    expect(onCancel).toHaveBeenCalled();
  });
});
