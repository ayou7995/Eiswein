import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { screen } from '@testing-library/react';
import { SidebarStatusCard } from './SidebarStatusCard';
import { renderWithProviders } from '../test/utils';
import { ROUTES } from '../lib/constants';
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

function primePosture(data: MarketPostureResponse | undefined, isLoading = false): void {
  mockPosture.mockReturnValue({
    data,
    isLoading,
    isError: false,
    error: null,
    refetch: vi.fn(),
  } as unknown as ReturnType<typeof useMarketPosture>);
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

describe('SidebarStatusCard — 2-row tinted variant', () => {
  it('renders posture, days, vote counts, and freshness across 2 rows', () => {
    primePosture(makePosture());
    renderWithProviders(<SidebarStatusCard />, {
      routerInitialEntries: [ROUTES.HISTORY],
    });

    const card = screen.getByTestId('sidebar-status-card');
    expect(card).toHaveTextContent('進攻');
    expect(card).toHaveTextContent('34 天');
    // Counts now use the verbose "買 X 持 X 賣 X" form (legible at text-xs).
    expect(card).toHaveTextContent('買 3');
    expect(card).toHaveTextContent('持 1');
    expect(card).toHaveTextContent('賣 0');
    expect(screen.getByTestId('data-freshness-badge')).toBeInTheDocument();
  });

  it.each([
    ['offensive', 'bg-emerald-50'],
    ['normal', 'bg-amber-50'],
    ['defensive', 'bg-rose-50'],
  ] as const)(
    'tints the card background per posture (%s → %s)',
    (posture, expectedClass) => {
      primePosture(makePosture({ posture, posture_label: posture }));
      renderWithProviders(<SidebarStatusCard />, {
        routerInitialEntries: [ROUTES.HISTORY],
      });
      expect(screen.getByTestId('sidebar-status-card').className).toContain(
        expectedClass,
      );
    },
  );

  it('is fully suppressed on the MarketOverview route to avoid duplication', () => {
    primePosture(makePosture());
    renderWithProviders(<SidebarStatusCard />, {
      routerInitialEntries: [ROUTES.DASHBOARD],
    });
    expect(screen.queryByTestId('sidebar-status-card')).not.toBeInTheDocument();
    expect(
      screen.queryByTestId('sidebar-status-card-loading'),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByTestId('sidebar-status-card-empty'),
    ).not.toBeInTheDocument();
  });

  it('renders on TickerDetail / History / Settings (non-dashboard routes)', () => {
    primePosture(makePosture());
    for (const path of [ROUTES.HISTORY, ROUTES.SETTINGS, '/ticker/SPY']) {
      const { unmount } = renderWithProviders(<SidebarStatusCard />, {
        routerInitialEntries: [path],
      });
      expect(screen.getByTestId('sidebar-status-card')).toBeInTheDocument();
      unmount();
    }
  });

  it('renders loading stub on non-dashboard routes', () => {
    primePosture(undefined, true);
    renderWithProviders(<SidebarStatusCard />, {
      routerInitialEntries: [ROUTES.HISTORY],
    });
    expect(screen.getByTestId('sidebar-status-card-loading')).toBeInTheDocument();
  });

  it('renders empty stub on non-dashboard routes when posture has not run', () => {
    primePosture(undefined);
    renderWithProviders(<SidebarStatusCard />, {
      routerInitialEntries: [ROUTES.HISTORY],
    });
    expect(screen.getByTestId('sidebar-status-card-empty')).toBeInTheDocument();
  });

  it('suppresses loading + empty stubs on the dashboard route too', () => {
    primePosture(undefined, true);
    const { unmount } = renderWithProviders(<SidebarStatusCard />, {
      routerInitialEntries: [ROUTES.DASHBOARD],
    });
    expect(
      screen.queryByTestId('sidebar-status-card-loading'),
    ).not.toBeInTheDocument();
    unmount();

    primePosture(undefined);
    renderWithProviders(<SidebarStatusCard />, {
      routerInitialEntries: [ROUTES.DASHBOARD],
    });
    expect(
      screen.queryByTestId('sidebar-status-card-empty'),
    ).not.toBeInTheDocument();
  });

  it('provides ARIA labels so screen-readers spell out counts and streak', () => {
    primePosture(
      makePosture({ regime_green_count: 2, regime_yellow_count: 0, regime_red_count: 2 }),
    );
    renderWithProviders(<SidebarStatusCard />, {
      routerInitialEntries: [ROUTES.HISTORY],
    });
    expect(
      screen.getByLabelText('綠燈 2、黃燈 0、紅燈 2'),
    ).toBeInTheDocument();
    expect(screen.getByLabelText('已持續 34 天')).toBeInTheDocument();
  });
});
