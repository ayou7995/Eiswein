import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { screen } from '@testing-library/react';
import { SidebarStatusCard } from './SidebarStatusCard';
import { renderWithProviders } from '../test/utils';
import type { MarketPostureResponse } from '../api/marketPosture';
import type { SystemInfoResponse } from '../api/settings';

vi.mock('../hooks/useMarketPosture', () => ({
  useMarketPosture: vi.fn(),
}));
vi.mock('../hooks/useSettings', () => ({
  useSystemInfo: vi.fn(),
}));

import { useMarketPosture } from '../hooks/useMarketPosture';
import { useSystemInfo } from '../hooks/useSettings';

const mockPosture = vi.mocked(useMarketPosture);
const mockSysInfo = vi.mocked(useSystemInfo);

function makePosture(overrides: Partial<MarketPostureResponse> = {}): MarketPostureResponse {
  return {
    posture: 'offensive',
    posture_label: '進攻',
    streak_days: 34,
    regime_green_count: 3,
    regime_yellow_count: 1,
    regime_red_count: 0,
    indicator_version: 'v1',
    snapshot_date: '2026-05-27',
    ...overrides,
  } as MarketPostureResponse;
}

function makeSysInfo(): SystemInfoResponse {
  return {
    db_size_bytes: 1024,
    watchlist_count: 18,
    snapshot_count: 100,
    last_signal_run_at: '2026-05-27T16:00:00-04:00',
    data_freshness: {
      latest_bar_date: '2026-05-27',
      latest_bar_age_days: 0,
      is_trading_day_today: true,
      is_intraday_partial: false,
      market_close_at: '2026-05-27T16:00:00-04:00',
      next_close_at: null,
    },
  } as unknown as SystemInfoResponse;
}

beforeEach(() => {
  mockSysInfo.mockReturnValue({
    data: makeSysInfo(),
    isLoading: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
  } as unknown as ReturnType<typeof useSystemInfo>);
});

afterEach(() => {
  vi.clearAllMocks();
});

describe('SidebarStatusCard — slim variant', () => {
  it('renders posture, days, and G/Y/R counts on a single row', () => {
    mockPosture.mockReturnValue({
      data: makePosture(),
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof useMarketPosture>);
    renderWithProviders(<SidebarStatusCard />);

    const card = screen.getByTestId('sidebar-status-card');
    expect(card).toHaveTextContent('進攻');
    expect(card).toHaveTextContent('34d');
    // Counts collapse to "G/Y/R" tabular form.
    expect(card).toHaveTextContent('3/1/0');
  });

  it('uses a distinct dot color for each posture (offensive/normal/defensive)', () => {
    for (const [posture, expectedClass] of [
      ['offensive', 'bg-emerald-500'],
      ['normal', 'bg-amber-500'],
      ['defensive', 'bg-rose-500'],
    ] as const) {
      mockPosture.mockReturnValue({
        data: makePosture({ posture, posture_label: posture }),
        isLoading: false,
        isError: false,
        error: null,
        refetch: vi.fn(),
      } as unknown as ReturnType<typeof useMarketPosture>);
      const { unmount } = renderWithProviders(<SidebarStatusCard />);
      const card = screen.getByTestId('sidebar-status-card');
      expect(card.innerHTML).toContain(expectedClass);
      unmount();
    }
  });

  it('renders loading single-row stub when posture is loading', () => {
    mockPosture.mockReturnValue({
      data: undefined,
      isLoading: true,
      isError: false,
      error: null,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof useMarketPosture>);
    renderWithProviders(<SidebarStatusCard />);
    expect(screen.getByTestId('sidebar-status-card-loading')).toBeInTheDocument();
  });

  it('renders empty single-row stub when posture has not run yet', () => {
    mockPosture.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof useMarketPosture>);
    renderWithProviders(<SidebarStatusCard />);
    expect(screen.getByTestId('sidebar-status-card-empty')).toBeInTheDocument();
  });

  it('embeds freshness badge inline when data_freshness present', () => {
    mockPosture.mockReturnValue({
      data: makePosture(),
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof useMarketPosture>);
    renderWithProviders(<SidebarStatusCard />);
    expect(screen.getByTestId('data-freshness-badge')).toBeInTheDocument();
  });

  it('provides ARIA labels for counts so screen-readers spell them out', () => {
    mockPosture.mockReturnValue({
      data: makePosture({ regime_green_count: 2, regime_yellow_count: 0, regime_red_count: 2 }),
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof useMarketPosture>);
    renderWithProviders(<SidebarStatusCard />);
    expect(
      screen.getByLabelText('綠燈 2、黃燈 0、紅燈 2'),
    ).toBeInTheDocument();
  });
});
