import { useRef, useState, type MouseEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { ROUTES } from '../../lib/constants';
import { ActionBadge } from '../ActionBadge';
import { EditTagsCard } from '../EditTagsCard';
import {
  useMoveSymbolToGroup,
  useWatchlistGroups,
} from '../../hooks/useWatchlistGroups';
import { useRemoveTicker } from '../../hooks/useWatchlist';
import type { WatchlistSignalRow } from '../../hooks/useDashboardWatchlistSignals';

interface WatchlistRowProps {
  row: WatchlistSignalRow;
}

// One ticker row in the sidebar's grouped watchlist. Shows: symbol, compact
// action chip (if signal ready), and tag chips on a second line if any. The
// chip's color already encodes tone — a separate dot would just duplicate
// that signal. A "..." menu on hover opens move-to-group / edit-tags / jump.
//
// Click on the row anywhere (except the "..." menu) navigates to the
// ticker-detail page.
export function WatchlistRow({ row }: WatchlistRowProps): JSX.Element {
  const navigate = useNavigate();
  const [menuOpen, setMenuOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [editAnchor, setEditAnchor] = useState<{ top: number; left: number } | null>(null);
  const menuButtonRef = useRef<HTMLButtonElement | null>(null);
  const moveGroup = useMoveSymbolToGroup();
  const remove = useRemoveTicker();
  const groupsQuery = useWatchlistGroups();

  const symbol = row.item.symbol;

  const handleRowClick = (event: MouseEvent<HTMLDivElement>): void => {
    // Ignore clicks that originated inside the dot-menu region.
    const target = event.target as HTMLElement;
    if (target.closest('[data-row-menu-region]')) return;
    navigate(ROUTES.TICKER.replace(':symbol', symbol));
  };

  const openEditCard = (): void => {
    setMenuOpen(false);
    const rect = menuButtonRef.current?.getBoundingClientRect();
    if (rect) {
      setEditAnchor({ top: rect.bottom + 4, left: rect.right - 280 });
    }
    setEditOpen(true);
  };

  return (
    <li className="relative">
      <div
        onClick={handleRowClick}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            navigate(ROUTES.TICKER.replace(':symbol', symbol));
          }
        }}
        aria-label={`查看 ${symbol} 詳細`}
        data-testid={`sidebar-row-${symbol}`}
        className="group flex w-full cursor-pointer flex-col gap-0.5 rounded-md px-2 py-1 hover:bg-stone-100"
      >
        <div className="flex items-center gap-2">
          <span className="font-mono text-sm font-semibold text-stone-900">
            {symbol}
          </span>
          <div className="ml-auto flex items-center gap-1">
            {row.status === 'ready' && row.signal && (
              <ActionBadge
                action={row.signal.action}
                timingBadge={row.signal.timing_badge}
                compact
              />
            )}
            <div data-row-menu-region className="relative">
              <button
                ref={menuButtonRef}
                type="button"
                aria-label={`${symbol} 操作選單`}
                aria-haspopup="menu"
                aria-expanded={menuOpen}
                onClick={(e) => {
                  e.stopPropagation();
                  setMenuOpen((v) => !v);
                }}
                className="rounded-md px-1 text-stone-400 opacity-0 hover:bg-stone-200 hover:text-stone-700 focus-visible:opacity-100 group-hover:opacity-100"
              >
                <span aria-hidden="true">⋯</span>
              </button>
              {menuOpen && (
                <ul
                  role="menu"
                  className="absolute right-0 top-full z-30 mt-1 flex w-44 flex-col rounded-md border border-stone-200 bg-white py-1 text-sm shadow-md"
                  onClick={(e) => e.stopPropagation()}
                >
                  <li
                    role="menuitem"
                    className="border-b border-stone-100 px-2 pb-1.5 pt-1 text-[11px] font-medium uppercase tracking-wide text-stone-400"
                  >
                    移至群組
                  </li>
                  <li>
                    <button
                      type="button"
                      role="menuitem"
                      onClick={() => {
                        setMenuOpen(false);
                        void moveGroup.mutateAsync({ symbol, groupId: null });
                      }}
                      className="w-full px-3 py-1 text-left text-sm text-stone-700 hover:bg-stone-100"
                    >
                      未分類
                    </button>
                  </li>
                  {(groupsQuery.data?.data ?? []).map((g) => (
                    <li key={g.id}>
                      <button
                        type="button"
                        role="menuitem"
                        onClick={() => {
                          setMenuOpen(false);
                          void moveGroup.mutateAsync({ symbol, groupId: g.id });
                        }}
                        className="w-full px-3 py-1 text-left text-sm text-stone-700 hover:bg-stone-100"
                      >
                        {g.name}
                      </button>
                    </li>
                  ))}
                  <li className="my-1 border-t border-stone-100" />
                  <li>
                    <button
                      type="button"
                      role="menuitem"
                      onClick={openEditCard}
                      className="w-full px-3 py-1 text-left text-sm text-stone-700 hover:bg-stone-100"
                    >
                      編輯標籤
                    </button>
                  </li>
                  <li>
                    <button
                      type="button"
                      role="menuitem"
                      onClick={() => {
                        setMenuOpen(false);
                        navigate(ROUTES.TICKER.replace(':symbol', symbol));
                      }}
                      className="w-full px-3 py-1 text-left text-sm text-stone-700 hover:bg-stone-100"
                    >
                      跳至個股
                    </button>
                  </li>
                  {!row.item.isSystem && (
                    <li>
                      <button
                        type="button"
                        role="menuitem"
                        onClick={() => {
                          setMenuOpen(false);
                          if (
                            window.confirm(
                              `確認要從觀察清單移除 ${symbol}？`,
                            )
                          ) {
                            void remove.mutateAsync(symbol);
                          }
                        }}
                        className="w-full px-3 py-1 text-left text-sm text-rose-600 hover:bg-rose-50"
                      >
                        從觀察清單移除
                      </button>
                    </li>
                  )}
                </ul>
              )}
            </div>
          </div>
        </div>
        {row.item.tags.length > 0 && (
          <ul className="flex flex-wrap gap-1">
            {row.item.tags.map((tag) => (
              <li
                key={tag.id}
                className="rounded-full border px-1.5 py-px text-[10px] leading-tight"
                style={{
                  borderColor: tag.color,
                  color: tag.color,
                  backgroundColor: `${tag.color}11`,
                }}
              >
                {tag.name}
              </li>
            ))}
          </ul>
        )}
      </div>
      {editOpen && (
        <EditTagsCard
          item={row.item}
          anchor={editAnchor}
          onClose={() => setEditOpen(false)}
        />
      )}
    </li>
  );
}
