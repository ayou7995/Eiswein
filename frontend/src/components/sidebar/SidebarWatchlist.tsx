import { useEffect, useMemo, useRef, useState } from 'react';
import { useDashboardWatchlistSignals } from '../../hooks/useDashboardWatchlistSignals';
import { useWatchlistGroups } from '../../hooks/useWatchlistGroups';
import type { SidebarFilterState } from '../../hooks/useSidebarFilter';
import type { WatchlistSignalRow } from '../../hooks/useDashboardWatchlistSignals';
import { GroupHeader } from './GroupHeader';
import { WatchlistRow } from './WatchlistRow';

interface SidebarWatchlistProps {
  filter: SidebarFilterState;
}

// Synthetic ID for the "未分類" bucket so collapse state and rendering can
// key by number consistently. Real group IDs are nonnegative; -1 is safe.
const UNGROUPED_ID = -1;
const COLLAPSE_STORAGE_KEY = 'eiswein.sidebar.collapsed-groups';

function loadCollapsed(): Set<number> {
  try {
    const raw = window.localStorage.getItem(COLLAPSE_STORAGE_KEY);
    if (!raw) return new Set();
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return new Set();
    return new Set(parsed.filter((v): v is number => typeof v === 'number'));
  } catch {
    return new Set();
  }
}

function saveCollapsed(ids: ReadonlySet<number>): void {
  try {
    window.localStorage.setItem(
      COLLAPSE_STORAGE_KEY,
      JSON.stringify(Array.from(ids)),
    );
  } catch {
    /* localStorage unavailable */
  }
}

// Filter behaviour:
//   - search: substring match against symbol (case-insensitive)
//   - activeTagIds: row must have ALL selected tags (AND semantics, intersection)
function rowMatches(
  row: WatchlistSignalRow,
  filter: SidebarFilterState,
): boolean {
  const search = filter.search.trim().toLowerCase();
  if (search && !row.item.symbol.toLowerCase().includes(search)) return false;
  if (filter.activeTagIds.size > 0) {
    const have = new Set(row.item.tags.map((t) => t.id));
    for (const wanted of filter.activeTagIds) {
      if (!have.has(wanted)) return false;
    }
  }
  return true;
}

// SidebarWatchlist — grouped, filterable, collapsible.
//
// Collapse-state machine has two sources of truth:
//
//   1. `userCollapsed` (persisted) — the user's standing intent. Updated on
//      every click; survives reloads via localStorage.
//   2. `clickedDuringFilter` (transient) — groups the user *clicked* during
//      the current filter session. Reset whenever the filter becomes
//      inactive. While the filter is active, groups in this set honor
//      `userCollapsed`; groups NOT in this set are auto-expanded whenever
//      they contain a match.
//
// This way: starting a search expands matching groups without losing the
// user's pre-search collapse layout, but if the user *manually* collapses a
// group during search, that intent persists when the filter clears (matches
// "honor 那個動作"). Conversely, when the filter goes idle the auto-expanded
// groups that the user never touched fall back to their original collapsed
// state ("沒在搜尋就恢復原本的樣子").
export function SidebarWatchlist({ filter }: SidebarWatchlistProps): JSX.Element {
  const { rows, watchlistLoading } = useDashboardWatchlistSignals();
  const groupsQuery = useWatchlistGroups();
  const [userCollapsed, setUserCollapsed] = useState<Set<number>>(() => loadCollapsed());
  const [clickedDuringFilter, setClickedDuringFilter] = useState<Set<number>>(
    () => new Set(),
  );
  const prevFilterActive = useRef<boolean>(filter.isFilterActive);

  useEffect(() => {
    saveCollapsed(userCollapsed);
  }, [userCollapsed]);

  // Reset the transient "clicked during filter" set whenever the filter
  // becomes inactive. We don't reset when the filter merely *changes* (e.g.
  // user typing more characters) — the same filter session continues.
  useEffect(() => {
    const wasActive = prevFilterActive.current;
    const isActive = filter.isFilterActive;
    if (wasActive && !isActive) {
      setClickedDuringFilter(new Set());
    }
    prevFilterActive.current = isActive;
  }, [filter.isFilterActive]);

  // Bucket rows by group, computing both filtered-matches and total per
  // group. Total drives the "2/8" badge denominator; matches drive the
  // body + auto-expand decision.
  const { matchedByGroup, totalByGroup, orderedGroupIds } = useMemo(() => {
    const groups = groupsQuery.data?.data ?? [];
    const matched = new Map<number, WatchlistSignalRow[]>();
    const total = new Map<number, number>();
    for (const g of groups) {
      matched.set(g.id, []);
      total.set(g.id, 0);
    }
    matched.set(UNGROUPED_ID, []);
    total.set(UNGROUPED_ID, 0);
    for (const row of rows) {
      const gid = row.item.groupId ?? UNGROUPED_ID;
      total.set(gid, (total.get(gid) ?? 0) + 1);
      if (!rowMatches(row, filter)) continue;
      const list = matched.get(gid);
      if (list) list.push(row);
      else matched.set(gid, [row]);
    }
    // Group display order: backend-defined position order, plus the
    // synthetic 未分類 bucket at the end IFF it has any rows at all
    // (filtered or otherwise). Matches today's behaviour.
    const ordered: number[] = groups.map((g) => g.id);
    if ((total.get(UNGROUPED_ID) ?? 0) > 0) ordered.push(UNGROUPED_ID);
    return { matchedByGroup: matched, totalByGroup: total, orderedGroupIds: ordered };
  }, [groupsQuery.data, rows, filter]);

  // Effective collapse decision per group. See state-machine comment above.
  const isCollapsed = (groupId: number, hasMatches: boolean): boolean => {
    if (!filter.isFilterActive) {
      return userCollapsed.has(groupId);
    }
    if (clickedDuringFilter.has(groupId)) {
      return userCollapsed.has(groupId);
    }
    if (hasMatches) return false;
    return userCollapsed.has(groupId);
  };

  const toggleGroup = (groupId: number, currentlyCollapsed: boolean): void => {
    const nextCollapsed = !currentlyCollapsed;
    setUserCollapsed((prev) => {
      const next = new Set(prev);
      if (nextCollapsed) next.add(groupId);
      else next.delete(groupId);
      return next;
    });
    if (filter.isFilterActive) {
      setClickedDuringFilter((prev) => {
        if (prev.has(groupId)) return prev;
        const next = new Set(prev);
        next.add(groupId);
        return next;
      });
    }
  };

  if (watchlistLoading && rows.length === 0) {
    return <p className="px-2 text-xs text-stone-400">載入觀察清單…</p>;
  }

  if (rows.length === 0) {
    return (
      <p className="px-2 text-xs text-stone-400">
        尚未加入任何標的。下方可新增。
      </p>
    );
  }

  // Whole-watchlist no-match state (filter active, every group has 0
  // matches). Centered to avoid the "blank panel" feeling on a tall
  // sidebar; offers a one-click clear that wipes both search + chips.
  const totalMatches = Array.from(matchedByGroup.values()).reduce(
    (sum, list) => sum + list.length,
    0,
  );
  if (filter.isFilterActive && totalMatches === 0) {
    return (
      <div
        data-testid="sidebar-no-matches"
        className="flex flex-col items-center gap-2 px-2 py-6 text-center"
      >
        <p className="text-xs text-stone-500">沒有符合條件的代碼</p>
        <button
          type="button"
          onClick={filter.clearAllFilters}
          className="rounded-md border border-stone-300 px-2 py-1 text-xs text-stone-700 hover:bg-stone-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500"
        >
          清除搜尋與標籤
        </button>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      {orderedGroupIds.map((groupId) => {
        const bucket = matchedByGroup.get(groupId) ?? [];
        const total = totalByGroup.get(groupId) ?? 0;
        // While filtering, suppress the entire group (header included)
        // when nothing in it matches. Without a filter, empty groups are
        // still rendered so the user has a reorder/delete target.
        if (filter.isFilterActive && bucket.length === 0) return null;
        const group =
          groupId === UNGROUPED_ID
            ? null
            : groupsQuery.data?.data.find((g) => g.id === groupId) ?? null;
        const collapsed = isCollapsed(groupId, bucket.length > 0);
        const countLabel = filter.isFilterActive
          ? `${bucket.length}/${total}`
          : `${total}`;
        return (
          <div key={groupId}>
            <GroupHeader
              group={group}
              countLabel={countLabel}
              collapsed={collapsed}
              onToggle={() => toggleGroup(groupId, collapsed)}
              siblingIdsInOrder={(groupsQuery.data?.data ?? []).map((g) => g.id)}
            />
            {!collapsed && (
              <ul className="flex flex-col">
                {bucket.length === 0 && !filter.isFilterActive && (
                  <li className="px-3 py-1 text-[11px] text-stone-400">
                    （目前沒有符合條件的標的）
                  </li>
                )}
                {bucket.map((row) => (
                  <WatchlistRow key={row.item.symbol} row={row} />
                ))}
              </ul>
            )}
          </div>
        );
      })}
    </div>
  );
}
