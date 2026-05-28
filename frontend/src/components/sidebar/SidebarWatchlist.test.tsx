import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SidebarWatchlist } from './SidebarWatchlist';
import { renderWithProviders } from '../../test/utils';
import type {
  SidebarFilterState,
} from '../../hooks/useSidebarFilter';
import type {
  WatchlistSignalRow,
  DashboardWatchlistSignals,
} from '../../hooks/useDashboardWatchlistSignals';
import type { WatchlistItem } from '../../api/watchlist';
import type {
  WatchlistGroup,
  GroupListResponse,
} from '../../api/watchlistGroups';

vi.mock('../../hooks/useDashboardWatchlistSignals', () => ({
  useDashboardWatchlistSignals: vi.fn(),
}));
vi.mock('../../hooks/useWatchlistGroups', () => ({
  useWatchlistGroups: vi.fn(),
  useMoveSymbolToGroup: vi.fn(),
  useRenameWatchlistGroup: vi.fn(),
  useDeleteWatchlistGroup: vi.fn(),
  useReorderWatchlistGroups: vi.fn(),
}));
vi.mock('../../hooks/useWatchlist', () => ({
  useRemoveTicker: vi.fn(),
}));

import { useDashboardWatchlistSignals } from '../../hooks/useDashboardWatchlistSignals';
import {
  useWatchlistGroups,
  useMoveSymbolToGroup,
  useRenameWatchlistGroup,
  useDeleteWatchlistGroup,
  useReorderWatchlistGroups,
} from '../../hooks/useWatchlistGroups';
import { useRemoveTicker } from '../../hooks/useWatchlist';

const mockSignals = vi.mocked(useDashboardWatchlistSignals);
const mockGroups = vi.mocked(useWatchlistGroups);
const mockMoveGroup = vi.mocked(useMoveSymbolToGroup);
const mockRenameGroup = vi.mocked(useRenameWatchlistGroup);
const mockDeleteGroup = vi.mocked(useDeleteWatchlistGroup);
const mockReorderGroups = vi.mocked(useReorderWatchlistGroups);
const mockRemoveTicker = vi.mocked(useRemoveTicker);

function makeMutation<T>(): T {
  return {
    mutate: vi.fn(),
    mutateAsync: vi.fn().mockResolvedValue(undefined),
    isPending: false,
    isError: false,
    isSuccess: false,
    error: null,
    reset: vi.fn(),
  } as unknown as T;
}

function makeItem(overrides: Partial<WatchlistItem>): WatchlistItem {
  return {
    symbol: overrides.symbol ?? 'AAA',
    dataStatus: 'ready',
    addedAt: new Date('2026-04-01T00:00:00Z'),
    lastRefreshAt: new Date('2026-04-21T21:00:00Z'),
    isSystem: false,
    activeOnboardingJobId: null,
    groupId: null,
    groupName: null,
    tags: [],
    ...overrides,
  };
}

function makeRow(item: WatchlistItem): WatchlistSignalRow {
  return {
    item,
    status: 'pending_signal',
    signal: null,
    error: null,
  };
}

function makeGroups(groups: WatchlistGroup[]): GroupListResponse {
  return { data: groups, total: groups.length };
}

function makeFilter(overrides: Partial<SidebarFilterState> = {}): SidebarFilterState {
  return {
    activeTagIds: new Set(),
    search: '',
    isFilterActive: false,
    toggleTag: vi.fn(),
    clearAll: vi.fn(),
    clearAllFilters: vi.fn(),
    setSearch: vi.fn(),
    ...overrides,
  };
}

// jsdom in this project ships without a real Storage implementation —
// `window.localStorage` is just `{}`. Install a minimal in-memory shim so
// the persisted-collapse-state tests can prime data and so the component's
// `setItem` writes don't no-op silently inside their try/catch (which would
// hide bugs in our state-machine).
function installFakeLocalStorage(): void {
  const store = new Map<string, string>();
  const shim = {
    getItem: (k: string): string | null => (store.has(k) ? store.get(k) ?? null : null),
    setItem: (k: string, v: string): void => {
      store.set(k, String(v));
    },
    removeItem: (k: string): void => {
      store.delete(k);
    },
    clear: (): void => {
      store.clear();
    },
    key: (i: number): string | null => Array.from(store.keys())[i] ?? null,
    get length(): number {
      return store.size;
    },
  };
  Object.defineProperty(window, 'localStorage', {
    value: shim,
    configurable: true,
  });
}

beforeEach(() => {
  installFakeLocalStorage();
  // Common mutation mocks shared by all tests — GroupHeader and WatchlistRow
  // import these even when the relevant menu is never opened.
  mockMoveGroup.mockReturnValue(makeMutation<ReturnType<typeof useMoveSymbolToGroup>>());
  mockRenameGroup.mockReturnValue(makeMutation<ReturnType<typeof useRenameWatchlistGroup>>());
  mockDeleteGroup.mockReturnValue(makeMutation<ReturnType<typeof useDeleteWatchlistGroup>>());
  mockReorderGroups.mockReturnValue(makeMutation<ReturnType<typeof useReorderWatchlistGroups>>());
  mockRemoveTicker.mockReturnValue(makeMutation<ReturnType<typeof useRemoveTicker>>());
});

afterEach(() => {
  vi.clearAllMocks();
});

describe('SidebarWatchlist — filter behaviour', () => {
  const coreGroup: WatchlistGroup = { id: 1, name: 'Core', position: 0, symbol_count: 2 };
  const watchingGroup: WatchlistGroup = { id: 2, name: 'Watching', position: 1, symbol_count: 2 };

  const rows: WatchlistSignalRow[] = [
    makeRow(makeItem({ symbol: 'TSLA', groupId: 1, groupName: 'Core' })),
    makeRow(makeItem({ symbol: 'NVDA', groupId: 1, groupName: 'Core' })),
    makeRow(makeItem({ symbol: 'SPY', groupId: 2, groupName: 'Watching' })),
    makeRow(makeItem({ symbol: 'QQQ', groupId: 2, groupName: 'Watching' })),
  ];

  function primeData(): void {
    mockSignals.mockReturnValue({
      rows,
      watchlistLoading: false,
      watchlistError: false,
      refetchWatchlist: vi.fn(),
    } as DashboardWatchlistSignals);
    mockGroups.mockReturnValue({
      data: makeGroups([coreGroup, watchingGroup]),
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof useWatchlistGroups>);
  }

  it('shows all groups with plain total counts when filter is idle', () => {
    primeData();
    renderWithProviders(<SidebarWatchlist filter={makeFilter()} />);

    expect(screen.getByText('Core')).toBeInTheDocument();
    expect(screen.getByText('Watching')).toBeInTheDocument();
    // Counts are plain "N", not "N/M", when the filter is idle. Both groups
    // have 2 rows → two matching badges.
    expect(screen.getAllByLabelText('2 項')).toHaveLength(2);
    // All 4 rows visible.
    expect(screen.getByTestId('sidebar-row-TSLA')).toBeInTheDocument();
    expect(screen.getByTestId('sidebar-row-NVDA')).toBeInTheDocument();
    expect(screen.getByTestId('sidebar-row-SPY')).toBeInTheDocument();
    expect(screen.getByTestId('sidebar-row-QQQ')).toBeInTheDocument();
  });

  it('hides groups with zero matches and shows N/M counts when filtering', () => {
    primeData();
    renderWithProviders(
      <SidebarWatchlist
        filter={makeFilter({ search: 'TSL', isFilterActive: true })}
      />,
    );

    // Core (TSLA matches) stays; Watching disappears entirely (header + body).
    expect(screen.getByText('Core')).toBeInTheDocument();
    expect(screen.queryByText('Watching')).not.toBeInTheDocument();
    expect(screen.getByLabelText('1/2 項', { selector: 'span' })).toBeInTheDocument();
    expect(screen.getByTestId('sidebar-row-TSLA')).toBeInTheDocument();
    expect(screen.queryByTestId('sidebar-row-NVDA')).not.toBeInTheDocument();
  });

  it('renders centered empty state with one-click clear when no group has matches', async () => {
    const user = userEvent.setup();
    primeData();
    const clearAll = vi.fn();
    renderWithProviders(
      <SidebarWatchlist
        filter={makeFilter({
          search: 'ZZZZ',
          isFilterActive: true,
          clearAllFilters: clearAll,
        })}
      />,
    );

    const empty = screen.getByTestId('sidebar-no-matches');
    expect(within(empty).getByText('沒有符合條件的代碼')).toBeInTheDocument();
    await user.click(within(empty).getByRole('button', { name: '清除搜尋與標籤' }));
    expect(clearAll).toHaveBeenCalledTimes(1);
  });

  it('auto-expands a previously collapsed group when a search lands inside it', async () => {
    primeData();
    window.localStorage.setItem(
      'eiswein.sidebar.collapsed-groups',
      JSON.stringify([1]),
    );

    // First render: filter idle, Core is collapsed (TSLA hidden).
    const { rerender } = renderWithProviders(
      <SidebarWatchlist filter={makeFilter()} />,
    );
    expect(screen.queryByTestId('sidebar-row-TSLA')).not.toBeInTheDocument();

    // Activate filter: Core has a match → should auto-expand.
    rerender(
      <SidebarWatchlist
        filter={makeFilter({ search: 'TSL', isFilterActive: true })}
      />,
    );
    expect(screen.getByTestId('sidebar-row-TSLA')).toBeInTheDocument();
  });

  it('honors collapse toggled during filter and restores pre-filter state otherwise', async () => {
    const user = userEvent.setup();
    primeData();

    // No persisted collapse state — both groups start expanded.
    const filterIdle = makeFilter();
    const filterActive = makeFilter({ search: 'TS', isFilterActive: true });
    const { rerender } = renderWithProviders(
      <SidebarWatchlist filter={filterIdle} />,
    );
    expect(screen.getByTestId('sidebar-row-TSLA')).toBeInTheDocument();
    expect(screen.getByTestId('sidebar-row-NVDA')).toBeInTheDocument();
    expect(screen.getByTestId('sidebar-row-SPY')).toBeInTheDocument();

    // Activate filter — Watching disappears (no match), Core stays expanded
    // with TSLA visible. User then collapses Core during the filter session.
    rerender(<SidebarWatchlist filter={filterActive} />);
    await user.click(screen.getByRole('button', { name: /收合 Core 群組/ }));
    // Core is now collapsed during filter — TSLA hidden again.
    expect(screen.queryByTestId('sidebar-row-TSLA')).not.toBeInTheDocument();

    // Clear filter — both groups visible. Core was clicked during filter so
    // its collapsed state persists ("honor latest action"). Watching never
    // touched → original expanded state restored.
    rerender(<SidebarWatchlist filter={filterIdle} />);
    expect(screen.queryByTestId('sidebar-row-TSLA')).not.toBeInTheDocument();
    expect(screen.queryByTestId('sidebar-row-NVDA')).not.toBeInTheDocument();
    expect(screen.getByTestId('sidebar-row-SPY')).toBeInTheDocument();
    expect(screen.getByTestId('sidebar-row-QQQ')).toBeInTheDocument();
  });

  it('reverts auto-expansion without persistence when the user never clicks during filter', () => {
    primeData();
    window.localStorage.setItem(
      'eiswein.sidebar.collapsed-groups',
      JSON.stringify([1]),
    );

    const filterIdle = makeFilter();
    const filterActive = makeFilter({ search: 'TSL', isFilterActive: true });
    const { rerender } = renderWithProviders(
      <SidebarWatchlist filter={filterIdle} />,
    );
    expect(screen.queryByTestId('sidebar-row-TSLA')).not.toBeInTheDocument();

    rerender(<SidebarWatchlist filter={filterActive} />);
    expect(screen.getByTestId('sidebar-row-TSLA')).toBeInTheDocument();

    // Filter cleared — Core falls back to its persisted collapsed state.
    rerender(<SidebarWatchlist filter={filterIdle} />);
    expect(screen.queryByTestId('sidebar-row-TSLA')).not.toBeInTheDocument();
  });
});
