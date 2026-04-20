import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { PostureTimelineChart } from './PostureTimelineChart';

describe('PostureTimelineChart', () => {
  it('renders the strip with summary stats', () => {
    render(
      <PostureTimelineChart
        data={[
          { date: '2026-04-15', posture: 'offensive', regime_green_count: 3, regime_red_count: 1, regime_yellow_count: 0 },
          { date: '2026-04-16', posture: 'normal', regime_green_count: 2, regime_red_count: 1, regime_yellow_count: 1 },
          { date: '2026-04-17', posture: 'defensive', regime_green_count: 1, regime_red_count: 3, regime_yellow_count: 0 },
        ]}
      />,
    );
    expect(screen.getByTestId('posture-timeline')).toBeInTheDocument();
    const svg = screen.getByRole('img');
    expect(svg).toHaveAttribute('aria-label', expect.stringContaining('2026-04-15'));
    expect(svg).toHaveAttribute('aria-label', expect.stringContaining('2026-04-17'));

    // Summary dl surfaces the three counts.
    expect(screen.getByText('進攻')).toBeInTheDocument();
    expect(screen.getByText('正常')).toBeInTheDocument();
    expect(screen.getByText('防守')).toBeInTheDocument();
  });

  it('renders the empty state when there is no data', () => {
    render(<PostureTimelineChart data={[]} />);
    expect(screen.getByTestId('posture-timeline-empty')).toHaveTextContent('無市場態勢歷史');
  });
});
