import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ActionBadgePair } from './ActionBadgePair';

describe('ActionBadgePair', () => {
  it('renders mid + short labels and two ActionBadge instances', () => {
    render(
      <ActionBadgePair
        midAction="hold"
        midGreen={2}
        midRed={1}
        midTimingBadge="✓ 時機好"
        shortAction="buy"
        shortGreen={3}
        shortRed={0}
      />,
    );

    // Both timeframe chips appear with their own data-tone.
    expect(screen.getByTestId('action-badge-pair-label-mid')).toHaveTextContent(
      '中期',
    );
    expect(screen.getByTestId('action-badge-pair-label-short')).toHaveTextContent(
      '短期',
    );

    // Both ActionBadge instances render; data-action carries the verdict
    // string so vote counts remain testable separately.
    const badges = screen.getAllByTestId('action-badge');
    expect(badges).toHaveLength(2);
    expect(badges[0]).toHaveAttribute('data-action', 'hold');
    expect(badges[1]).toHaveAttribute('data-action', 'buy');
  });

  it('passes the timing badge to the mid action only', () => {
    render(
      <ActionBadgePair
        midAction="buy"
        midGreen={3}
        midRed={0}
        midTimingBadge="✓ 時機好"
        shortAction="hold"
        shortGreen={2}
        shortRed={1}
      />,
    );
    // The timing badge slot is part of the mid ActionBadge; the short
    // badge has no timing modifier (D1b applies to the mid vote only).
    const timingBadges = screen.getAllByTestId('action-badge-timing');
    expect(timingBadges).toHaveLength(1);
    expect(timingBadges[0]).toHaveTextContent('✓ 時機好');
  });

  it('renders even when the two verdicts disagree (the feature)', () => {
    // Real scenario from 2026-06-05: mid says 觀望 (long-term picture
    // weakening) but the panic VIX spike + RSI 26 → short says 🟢 買入.
    // UI must surface both so the operator can act tactically.
    render(
      <ActionBadgePair
        midAction="watch"
        midGreen={1}
        midRed={2}
        shortAction="buy"
        shortGreen={3}
        shortRed={1}
      />,
    );
    const badges = screen.getAllByTestId('action-badge');
    expect(badges[0]).toHaveAttribute('data-action', 'watch');
    expect(badges[1]).toHaveAttribute('data-action', 'buy');
  });

  it('flattens both sides when compact=true', () => {
    render(
      <ActionBadgePair
        midAction="buy"
        midGreen={3}
        midRed={0}
        shortAction="hold"
        shortGreen={2}
        shortRed={1}
        compact
      />,
    );
    const badges = screen.getAllByTestId('action-badge');
    for (const badge of badges) {
      expect(badge).toHaveAttribute('data-compact', 'true');
    }
  });
});
