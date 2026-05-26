import { useEffect, useMemo, useState } from 'react';
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

// Groups + filtered rows. Filter behaviour:
//   - search: substring match against symbol (case-insensitive)
//   - activeTagIds: row must have ALL selected tags (AND semantics, intersection)
// The "未分類" bucket appears at the bottom only when it has at least one
// (filtered) row.
function filterRow(
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

export function SidebarWatchlist({ filter }: SidebarWatchlistProps): JSX.Element {
  const { rows, watchlistLoading } = useDashboardWatchlistSignals();
  const groupsQuery = useWatchlistGroups();
  const [collapsed, setCollapsed] = useState<Set<number>>(() => loadCollapsed());

  useEffect(() => {
    saveCollapsed(collapsed);
  }, [collapsed]);

  // Bucket the filtered rows by group_id (null → UNGROUPED_ID). Symbols
  // within a group remain in watchlist order (alphabetical by default on
  // the backend); we don't add another sort here.
  const { buckets, orderedGroupIds } = useMemo(() => {
    const groups = groupsQuery.data?.data ?? [];
    const byId = new Map<number, WatchlistSignalRow[]>();
    // Seed every group so empty groups still render with count 0 — gives
    // the user a visible reorder/delete target.
    for (const g of groups) byId.set(g.id, []);
    byId.set(UNGROUPED_ID, []);
    for (const row of rows) {
      if (!filterRow(row, filter)) continue;
      const gid = row.item.groupId ?? UNGROUPED_ID;
      const list = byId.get(gid);
      if (list) list.push(row);
      else byId.set(gid, [row]);
    }
    const ordered: number[] = groups.map((g) => g.id);
    if ((byId.get(UNGROUPED_ID) ?? []).length > 0) ordered.push(UNGROUPED_ID);
    return { buckets: byId, orderedGroupIds: ordered };
  }, [groupsQuery.data, rows, filter]);

  const toggleGroup = (groupId: number): void => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(groupId)) next.delete(groupId);
      else next.add(groupId);
      return next;
    });
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

  return (
    <div className="flex flex-col gap-2">
      {orderedGroupIds.map((groupId) => {
        const bucket = buckets.get(groupId) ?? [];
        const group =
          groupId === UNGROUPED_ID
            ? null
            : groupsQuery.data?.data.find((g) => g.id === groupId) ?? null;
        const isCollapsed = collapsed.has(groupId);
        return (
          <div key={groupId}>
            <GroupHeader
              group={group}
              count={bucket.length}
              collapsed={isCollapsed}
              onToggle={() => toggleGroup(groupId)}
              siblingIdsInOrder={(groupsQuery.data?.data ?? []).map((g) => g.id)}
            />
            {!isCollapsed && (
              <ul className="flex flex-col">
                {bucket.length === 0 && (
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
