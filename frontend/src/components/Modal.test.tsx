import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Modal } from './Modal';

describe('Modal', () => {
  it('does not render when closed', () => {
    render(
      <Modal open={false} onClose={() => {}} title="hello">
        <p>body</p>
      </Modal>,
    );
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('renders a dialog with the given title when open', () => {
    render(
      <Modal open onClose={() => {}} title="測試對話框">
        <button type="button">first</button>
        <button type="button">second</button>
      </Modal>,
    );
    const dialog = screen.getByRole('dialog');
    expect(dialog).toHaveAttribute('aria-modal', 'true');
    expect(screen.getByText('測試對話框')).toBeInTheDocument();
  });

  it('closes on escape', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(
      <Modal open onClose={onClose} title="測試">
        <button type="button">action</button>
      </Modal>,
    );
    await user.keyboard('{Escape}');
    expect(onClose).toHaveBeenCalled();
  });

  it('closes on backdrop click', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(
      <Modal open onClose={onClose} title="測試">
        <button type="button">action</button>
      </Modal>,
    );
    const backdrop = screen.getByTestId('modal-backdrop');
    await user.click(backdrop);
    expect(onClose).toHaveBeenCalled();
  });

  it('closes when the close button is clicked', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(
      <Modal open onClose={onClose} title="測試">
        <p>content</p>
      </Modal>,
    );
    await user.click(screen.getByLabelText('關閉對話框'));
    expect(onClose).toHaveBeenCalled();
  });
});
