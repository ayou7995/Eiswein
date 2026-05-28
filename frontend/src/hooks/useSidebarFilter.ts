// useSidebarFilter — shared state for the sidebar's tag chip filter row and
// search input. Persisted to localStorage so the user keeps the same filter
// shape across reloads (the operator routinely jumps between Market Overview
// → Ticker → back, and re-applying chip selections each time is annoying).
//
// State shape:
//   activeTagIds: Set<number>  — empty = "全部" (no filter)
//   search: string             — substring match against symbol (case-insensitive)
//
// Why a custom hook rather than React Query / context: this is pure UI state,
// not server state. Two components (TagFilterRow + SidebarWatchlist) read it,
// AppShell hosts neither — a hook keeps the wiring local without forcing a
// provider above AppShell.

import { useCallback, useEffect, useMemo, useState } from 'react';

const STORAGE_KEY = 'eiswein.sidebar.filter';

interface PersistedFilter {
  activeTagIds: number[];
  search: string;
}

function loadFilter(): PersistedFilter {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return { activeTagIds: [], search: '' };
    const parsed = JSON.parse(raw) as unknown;
    if (typeof parsed !== 'object' || parsed === null) {
      return { activeTagIds: [], search: '' };
    }
    const obj = parsed as Record<string, unknown>;
    const ids = Array.isArray(obj['activeTagIds'])
      ? obj['activeTagIds'].filter((v): v is number => typeof v === 'number')
      : [];
    const search = typeof obj['search'] === 'string' ? obj['search'] : '';
    return { activeTagIds: ids, search };
  } catch {
    return { activeTagIds: [], search: '' };
  }
}

function saveFilter(state: PersistedFilter): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    // localStorage unavailable (private browsing / quota) — non-fatal.
  }
}

export interface SidebarFilterState {
  activeTagIds: ReadonlySet<number>;
  search: string;
  // True when either a tag chip is active OR the search input has
  // non-whitespace content. Drives the sidebar's "hide empty groups +
  // auto-expand matches" mode.
  isFilterActive: boolean;
  toggleTag: (tagId: number) => void;
  clearAll: () => void;
  // Clears both tag chips AND the search input — used by the empty-state
  // "clear filter" button so the user doesn't have to clear two places.
  clearAllFilters: () => void;
  setSearch: (value: string) => void;
}

export function useSidebarFilter(): SidebarFilterState {
  const initial = useMemo(loadFilter, []);
  const [activeTagIds, setActiveTagIds] = useState<Set<number>>(
    () => new Set(initial.activeTagIds),
  );
  const [search, setSearchValue] = useState<string>(initial.search);

  useEffect(() => {
    saveFilter({
      activeTagIds: Array.from(activeTagIds),
      search,
    });
  }, [activeTagIds, search]);

  const toggleTag = useCallback((tagId: number): void => {
    setActiveTagIds((prev) => {
      const next = new Set(prev);
      if (next.has(tagId)) next.delete(tagId);
      else next.add(tagId);
      return next;
    });
  }, []);

  const clearAll = useCallback((): void => {
    setActiveTagIds(new Set());
  }, []);

  const clearAllFilters = useCallback((): void => {
    setActiveTagIds(new Set());
    setSearchValue('');
  }, []);

  const setSearch = useCallback((value: string): void => {
    setSearchValue(value);
  }, []);

  const isFilterActive = search.trim().length > 0 || activeTagIds.size > 0;

  return {
    activeTagIds,
    search,
    isFilterActive,
    toggleTag,
    clearAll,
    clearAllFilters,
    setSearch,
  };
}
