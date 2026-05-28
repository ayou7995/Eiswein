import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ActionBadge } from './ActionBadge';

describe('ActionBadge', () => {
  it.each([
    ['strong_buy', '🟢🟢', '強力買入', 'S'],
    ['buy', '🟢', '買入', 'B'],
    ['hold', '✓', '持有', 'H'],
    ['watch', '👀', '觀望', 'W'],
    ['reduce', '⚠️', '減倉', 'D'],
    ['exit', '🔴🔴', '出場', 'E'],
  ] as const)('renders %s with triple redundancy', (action, emoji, label, letter) => {
    render(<ActionBadge action={action} />);
    const badge = screen.getByTestId('action-badge');
    expect(badge).toHaveAttribute('data-action', action);
    expect(badge).toHaveTextContent(emoji);
    expect(badge).toHaveTextContent(label);
    expect(badge).toHaveTextContent(letter);
  });

  it('renders timing badge when provided', () => {
    render(<ActionBadge action="buy" timingBadge="✓ 時機好" />);
    expect(screen.getByTestId('action-badge-timing')).toHaveTextContent('✓ 時機好');
    expect(screen.getByRole('status')).toHaveAccessibleName(
      '建議動作：買入，時機提示：✓ 時機好',
    );
  });

  it('omits timing badge when null (server-side suppression honored)', () => {
    render(<ActionBadge action="exit" timingBadge={null} />);
    expect(screen.queryByTestId('action-badge-timing')).toBeNull();
  });

  it('includes an ARIA label suitable for screen readers', () => {
    render(<ActionBadge action="strong_buy" />);
    expect(screen.getByRole('status')).toHaveAccessibleName('建議動作：強力買入');
  });

  describe('compact variant', () => {
    it.each([
      ['strong_buy', '⏫', '強買'],
      ['buy', '🟢', '買入'],
      ['hold', '✓', '持有'],
      ['watch', '👀', '觀望'],
      ['reduce', '⚠', '減倉'],
      ['exit', '🔴', '出場'],
    ] as const)(
      'renders %s with single emoji + 2-char label (no letter)',
      (action, emoji, label) => {
        render(<ActionBadge action={action} compact />);
        const badge = screen.getByTestId('action-badge');
        expect(badge).toHaveAttribute('data-compact', 'true');
        expect(badge).toHaveTextContent(emoji);
        expect(badge).toHaveTextContent(label);
      },
    );

    it('keeps the same full ARIA label as the default variant for a11y', () => {
      render(<ActionBadge action="reduce" compact />);
      expect(screen.getByRole('status')).toHaveAccessibleName('建議動作：減倉');
    });

    it('uses distinct emojis for strong_buy vs buy so they are scannable', () => {
      const { rerender } = render(<ActionBadge action="strong_buy" compact />);
      const strongText = screen.getByTestId('action-badge').textContent ?? '';
      rerender(<ActionBadge action="buy" compact />);
      const buyText = screen.getByTestId('action-badge').textContent ?? '';
      expect(strongText).not.toEqual(buyText);
    });

    it('renders timing badge inline when provided', () => {
      render(<ActionBadge action="buy" timingBadge="✓ 時機好" compact />);
      expect(screen.getByTestId('action-badge-timing')).toHaveTextContent('✓ 時機好');
    });
  });
});
