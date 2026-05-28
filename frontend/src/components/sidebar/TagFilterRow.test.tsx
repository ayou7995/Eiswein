import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { TagFilterRow } from './TagFilterRow';
import { renderWithProviders } from '../../test/utils';
import type { SidebarFilterState } from '../../hooks/useSidebarFilter';
import type { WatchlistTag, TagListResponse } from '../../api/watchlistTags';
import type { WatchlistItem, WatchlistListResult } from '../../api/watchlist';

vi.mock('../../hooks/useWatchlistTags', () => ({
  useWatchlistTags: vi.fn(),
}));
vi.mock('../../hooks/useWatchlist', () => ({
  useWatchlist: vi.fn(),
}));

import { useWatchlistTags } from '../../hooks/useWatchlistTags';
import { useWatchlist } from '../../hooks/useWatchlist';

const mockTags = vi.mocked(useWatchlistTags);
const mockWatchlist = vi.mocked(useWatchlist);

function tag(id: number, name: string, color = '#10b981'): WatchlistTag {
  return { id, name, color };
}

function makeTagList(data: WatchlistTag[]): TagListResponse {
  return { data, total: data.length, popular: [] };
}

function makeItem(symbol: string, tags: WatchlistTag[]): WatchlistItem {
  return {
    symbol,
    dataStatus: 'ready',
    addedAt: new Date(),
    lastRefreshAt: null,
    isSystem: false,
    activeOnboardingJobId: null,
    groupId: null,
    groupName: null,
    tags,
  };
}

function makeWatchlist(items: WatchlistItem[]): WatchlistListResult {
  return { data: items, total: items.length, hasMore: false };
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

function primeTags(tags: WatchlistTag[]): void {
  mockTags.mockReturnValue({
    data: makeTagList(tags),
    isLoading: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
  } as unknown as ReturnType<typeof useWatchlistTags>);
}

function primeWatchlist(items: WatchlistItem[]): void {
  mockWatchlist.mockReturnValue({
    data: makeWatchlist(items),
    isLoading: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
  } as unknown as ReturnType<typeof useWatchlist>);
}

beforeEach(() => {
  primeWatchlist([]);
});

afterEach(() => {
  vi.clearAllMocks();
});

describe('TagFilterRow — overflow behaviour', () => {
  it('renders all tags inline when total ≤ 4 (no overflow trigger)', () => {
    primeTags([tag(1, 'AI'), tag(2, 'Semis'), tag(3, 'EV'), tag(4, 'Macro')]);
    renderWithProviders(<TagFilterRow filter={makeFilter()} />);

    expect(screen.getByRole('button', { name: 'AI' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Macro' })).toBeInTheDocument();
    expect(
      screen.queryByTestId('tag-filter-overflow-trigger'),
    ).not.toBeInTheDocument();
  });

  it('truncates to top-3 by frequency + ⋯N when total ≥ 5', () => {
    const ai = tag(1, 'AI');
    const semis = tag(2, 'Semis');
    const ev = tag(3, 'EV');
    const macro = tag(4, 'Macro');
    const defense = tag(5, '國防');
    primeTags([ai, semis, ev, macro, defense]);
    // AI on 4 tickers, Semis on 3, EV on 2, Macro on 1, 國防 on 1.
    primeWatchlist([
      makeItem('A', [ai, semis, ev]),
      makeItem('B', [ai, semis, macro]),
      makeItem('C', [ai, semis]),
      makeItem('D', [ai, ev, defense]),
    ]);
    renderWithProviders(<TagFilterRow filter={makeFilter()} />);

    expect(screen.getByRole('button', { name: 'AI' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Semis' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'EV' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Macro' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '國防' })).not.toBeInTheDocument();

    const trigger = screen.getByTestId('tag-filter-overflow-trigger');
    expect(trigger).toHaveAttribute(
      'aria-label',
      '顯示其他 2 個標籤',
    );
  });

  it('keeps active tags inline even when they are low-frequency', () => {
    const ai = tag(1, 'AI');
    const semis = tag(2, 'Semis');
    const ev = tag(3, 'EV');
    const macro = tag(4, 'Macro');
    const defense = tag(5, '國防');
    primeTags([ai, semis, ev, macro, defense]);
    primeWatchlist([
      makeItem('A', [ai, semis, ev]),
      makeItem('B', [ai, semis]),
      makeItem('C', [ai]),
    ]);
    // 國防 is least-used but actively filtering — must appear inline.
    renderWithProviders(
      <TagFilterRow
        filter={makeFilter({ activeTagIds: new Set([5]), isFilterActive: true })}
      />,
    );

    expect(screen.getByRole('button', { name: '國防' })).toBeInTheDocument();
    // 國防 took one slot → only 2 frequency picks shown (AI, Semis).
    expect(screen.getByRole('button', { name: 'AI' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Semis' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'EV' })).not.toBeInTheDocument();
    // Two tags in overflow (EV + Macro).
    expect(screen.getByTestId('tag-filter-overflow-trigger')).toHaveAttribute(
      'aria-label',
      '顯示其他 2 個標籤',
    );
  });

  it('opens popover with ALL tags and stays open across chip clicks', async () => {
    const user = userEvent.setup();
    const ai = tag(1, 'AI');
    const semis = tag(2, 'Semis');
    const ev = tag(3, 'EV');
    const macro = tag(4, 'Macro');
    const defense = tag(5, '國防');
    primeTags([ai, semis, ev, macro, defense]);
    primeWatchlist([
      makeItem('A', [ai]),
      makeItem('B', [ai]),
      makeItem('C', [semis]),
      makeItem('D', [ev]),
    ]);
    const toggle = vi.fn();
    renderWithProviders(
      <TagFilterRow filter={makeFilter({ toggleTag: toggle })} />,
    );

    await user.click(screen.getByTestId('tag-filter-overflow-trigger'));
    const popover = screen.getByTestId('tag-filter-overflow-popover');

    // Popover lists ALL 5 tags.
    expect(within(popover).getByRole('button', { name: 'AI' })).toBeInTheDocument();
    expect(within(popover).getByRole('button', { name: 'Macro' })).toBeInTheDocument();
    expect(within(popover).getByRole('button', { name: '國防' })).toBeInTheDocument();

    // Clicking a chip toggles + the popover stays open.
    await user.click(within(popover).getByRole('button', { name: 'Macro' }));
    expect(toggle).toHaveBeenCalledWith(4);
    expect(screen.getByTestId('tag-filter-overflow-popover')).toBeInTheDocument();
  });

  it('closes popover on ESC', async () => {
    const user = userEvent.setup();
    const tags = [tag(1, 'A'), tag(2, 'B'), tag(3, 'C'), tag(4, 'D'), tag(5, 'E')];
    primeTags(tags);
    renderWithProviders(<TagFilterRow filter={makeFilter()} />);

    await user.click(screen.getByTestId('tag-filter-overflow-trigger'));
    expect(screen.getByTestId('tag-filter-overflow-popover')).toBeInTheDocument();

    await user.keyboard('{Escape}');
    expect(
      screen.queryByTestId('tag-filter-overflow-popover'),
    ).not.toBeInTheDocument();
  });

  it('second click on the overflow trigger toggles the popover closed', async () => {
    const user = userEvent.setup();
    const tags = [tag(1, 'A'), tag(2, 'B'), tag(3, 'C'), tag(4, 'D'), tag(5, 'E')];
    primeTags(tags);
    renderWithProviders(<TagFilterRow filter={makeFilter()} />);

    const trigger = screen.getByTestId('tag-filter-overflow-trigger');
    await user.click(trigger);
    expect(screen.getByTestId('tag-filter-overflow-popover')).toBeInTheDocument();
    await user.click(trigger);
    expect(
      screen.queryByTestId('tag-filter-overflow-popover'),
    ).not.toBeInTheDocument();
  });
});
