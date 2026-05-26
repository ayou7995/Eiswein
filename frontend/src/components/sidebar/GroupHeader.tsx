import { useEffect, useRef, useState } from 'react';
import {
  useDeleteWatchlistGroup,
  useRenameWatchlistGroup,
  useReorderWatchlistGroups,
} from '../../hooks/useWatchlistGroups';
import type { WatchlistGroup } from '../../api/watchlistGroups';

interface GroupHeaderProps {
  group: WatchlistGroup | null;
  // When the header is for the synthetic "未分類" bucket, `group` is null —
  // the rename / reorder / delete menu is suppressed (nothing to mutate).
  count: number;
  collapsed: boolean;
  onToggle: () => void;
  // Order helpers — pass the current full list of group IDs in display order
  // so the reorder mutation can send the desired sequence. Passing the
  // siblings rather than a single neighbour keeps the API call atomic.
  siblingIdsInOrder: readonly number[];
}

// Collapsible group header. Shows ▼/▶ + name + count + "..." menu.
//
// Menu actions:
//   - 改名 → reveals an inline input that saves on Enter / blur.
//   - 調整順序 → submenu: 上移 / 下移. Reorder mutation sends the full
//     re-ordered ID list (backend assigns positions 0..N-1).
//   - 刪除群組 → window.confirm; orphan symbols go to group_id=NULL.
export function GroupHeader({
  group,
  count,
  collapsed,
  onToggle,
  siblingIdsInOrder,
}: GroupHeaderProps): JSX.Element {
  const [menuOpen, setMenuOpen] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [pendingName, setPendingName] = useState(group?.name ?? '');
  const inputRef = useRef<HTMLInputElement | null>(null);
  const rename = useRenameWatchlistGroup();
  const remove = useDeleteWatchlistGroup();
  const reorder = useReorderWatchlistGroups();

  useEffect(() => {
    if (renaming) {
      inputRef.current?.focus();
      inputRef.current?.select();
    }
  }, [renaming]);

  const commitRename = async (): Promise<void> => {
    if (!group) return;
    const trimmed = pendingName.trim();
    setRenaming(false);
    if (!trimmed || trimmed === group.name) return;
    try {
      await rename.mutateAsync({ groupId: group.id, name: trimmed });
    } catch (err) {
      console.error('rename group failed', err);
      setPendingName(group.name);
    }
  };

  const moveBy = async (offset: number): Promise<void> => {
    if (!group) return;
    setMenuOpen(false);
    const ids = [...siblingIdsInOrder];
    const idx = ids.indexOf(group.id);
    const target = idx + offset;
    if (idx < 0 || target < 0 || target >= ids.length) return;
    const taken = ids.splice(idx, 1);
    if (taken.length > 0 && typeof taken[0] === 'number') {
      ids.splice(target, 0, taken[0]);
    }
    try {
      await reorder.mutateAsync(ids);
    } catch (err) {
      console.error('reorder failed', err);
    }
  };

  const label = group ? group.name : '未分類';

  return (
    <div className="flex items-center gap-1 px-1 py-1 text-xs text-stone-600">
      <button
        type="button"
        aria-expanded={!collapsed}
        aria-label={`${collapsed ? '展開' : '收合'} ${label} 群組`}
        onClick={onToggle}
        className="inline-flex h-5 w-5 items-center justify-center rounded-md text-stone-400 hover:bg-stone-100 hover:text-stone-700"
      >
        <span aria-hidden="true">{collapsed ? '▶' : '▼'}</span>
      </button>
      {renaming && group ? (
        <input
          ref={inputRef}
          type="text"
          value={pendingName}
          onChange={(e) => setPendingName(e.target.value)}
          onBlur={() => void commitRename()}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault();
              void commitRename();
            } else if (e.key === 'Escape') {
              e.preventDefault();
              setPendingName(group.name);
              setRenaming(false);
            }
          }}
          className="flex-1 rounded-md border border-stone-300 bg-white px-1.5 py-0.5 text-xs text-stone-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-500"
        />
      ) : (
        <span className="flex-1 font-semibold uppercase tracking-wide">
          {label}
        </span>
      )}
      <span
        aria-label={`${count} 項`}
        className="rounded-full bg-stone-100 px-1.5 py-px text-[10px] text-stone-500"
      >
        {count}
      </span>
      {group && !renaming && (
        <div className="relative">
          <button
            type="button"
            aria-label={`${label} 操作選單`}
            aria-haspopup="menu"
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen((v) => !v)}
            className="rounded-md px-1 text-stone-400 hover:bg-stone-100 hover:text-stone-700"
          >
            <span aria-hidden="true">⋯</span>
          </button>
          {menuOpen && (
            <ul
              role="menu"
              className="absolute right-0 top-full z-30 mt-1 flex w-40 flex-col rounded-md border border-stone-200 bg-white py-1 text-sm shadow-md"
              onClick={(e) => e.stopPropagation()}
            >
              <li>
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => {
                    setMenuOpen(false);
                    setPendingName(group.name);
                    setRenaming(true);
                  }}
                  className="w-full px-3 py-1 text-left text-sm text-stone-700 hover:bg-stone-100"
                >
                  改名
                </button>
              </li>
              <li>
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => void moveBy(-1)}
                  className="w-full px-3 py-1 text-left text-sm text-stone-700 hover:bg-stone-100"
                >
                  上移
                </button>
              </li>
              <li>
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => void moveBy(1)}
                  className="w-full px-3 py-1 text-left text-sm text-stone-700 hover:bg-stone-100"
                >
                  下移
                </button>
              </li>
              <li className="my-1 border-t border-stone-100" />
              <li>
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => {
                    setMenuOpen(false);
                    if (
                      window.confirm(
                        `刪除「${group.name}」？群組內的標的會回到「未分類」。`,
                      )
                    ) {
                      void remove.mutateAsync(group.id);
                    }
                  }}
                  className="w-full px-3 py-1 text-left text-sm text-rose-600 hover:bg-rose-50"
                >
                  刪除群組
                </button>
              </li>
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
