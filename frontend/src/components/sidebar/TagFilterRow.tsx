import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useWatchlistTags } from '../../hooks/useWatchlistTags';
import { useWatchlist } from '../../hooks/useWatchlist';
import type { SidebarFilterState } from '../../hooks/useSidebarFilter';
import type { WatchlistTag } from '../../api/watchlistTags';

interface TagFilterRowProps {
  filter: SidebarFilterState;
}

// Beyond this many tags, the chip row truncates to the active set + the
// top-frequency picks (filling up to TARGET_VISIBLE), and the rest collapse
// behind a "⋯ N" popover. ≤4 tags always render inline because saving one
// chip slot in exchange for an extra click is a bad trade.
const OVERFLOW_THRESHOLD = 5;
const TARGET_VISIBLE = 3;

// Tag chip — shared between inline row and popover. Styled identically so
// toggling between the two places doesn't change a chip's appearance, only
// its position.
function TagChip({
  tag,
  active,
  onToggle,
}: {
  tag: WatchlistTag;
  active: boolean;
  onToggle: (id: number) => void;
}): JSX.Element {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={() => onToggle(tag.id)}
      className="rounded-full border px-2 py-0.5 text-xs font-medium transition"
      style={
        active
          ? { borderColor: tag.color, backgroundColor: `${tag.color}22`, color: tag.color }
          : { borderColor: '#e7e5e4', backgroundColor: '#ffffff', color: '#57534e' }
      }
    >
      {tag.name}
    </button>
  );
}

// Multi-select chip row with progressive disclosure.
//
// Layout: [全部] [active-tags…] [top-frequency-non-active…] [⋯ N]
//
// Visible-set algorithm (when total ≥ OVERFLOW_THRESHOLD):
//   1. All active tags inline — a hidden active filter is a UX trap.
//   2. Fill remaining slots up to TARGET_VISIBLE with the top-frequency
//      non-active tags (frequency = #tickers using that tag; tie → name).
//   3. Anything left → ⋯ N popover.
//
// Popover stays open across chip clicks so multi-toggling is fast. Closes
// on ESC, outside-click, or a second click on the ⋯ button.
export function TagFilterRow({ filter }: TagFilterRowProps): JSX.Element {
  const tagsQuery = useWatchlistTags();
  const watchlistQuery = useWatchlist();
  const [popoverOpen, setPopoverOpen] = useState(false);
  const overflowButtonRef = useRef<HTMLButtonElement | null>(null);
  const popoverRef = useRef<HTMLDivElement | null>(null);

  const tags = useMemo<readonly WatchlistTag[]>(
    () => tagsQuery.data?.data ?? [],
    [tagsQuery.data],
  );

  // Frequency = how many watchlist rows reference each tag. Computed from
  // the watchlist payload we're already fetching — no extra API call.
  const tagFrequency = useMemo<Map<number, number>>(() => {
    const counts = new Map<number, number>();
    const items = watchlistQuery.data?.data ?? [];
    for (const item of items) {
      for (const t of item.tags) {
        counts.set(t.id, (counts.get(t.id) ?? 0) + 1);
      }
    }
    return counts;
  }, [watchlistQuery.data]);

  const { visible, hidden } = useMemo(() => {
    if (tags.length < OVERFLOW_THRESHOLD) {
      return { visible: [...tags], hidden: [] as WatchlistTag[] };
    }
    const active = tags.filter((t) => filter.activeTagIds.has(t.id));
    const inactive = tags.filter((t) => !filter.activeTagIds.has(t.id));
    // Tie-break on name (case-insensitive) so display order is stable
    // across re-renders even when two tags share a frequency.
    const sortedInactive = [...inactive].sort((a, b) => {
      const fa = tagFrequency.get(a.id) ?? 0;
      const fb = tagFrequency.get(b.id) ?? 0;
      if (fa !== fb) return fb - fa;
      return a.name.localeCompare(b.name);
    });
    const slotsLeft = Math.max(0, TARGET_VISIBLE - active.length);
    const fill = sortedInactive.slice(0, slotsLeft);
    const visibleSet = [...active, ...fill];
    const visibleIds = new Set(visibleSet.map((t) => t.id));
    const hiddenSet = tags.filter((t) => !visibleIds.has(t.id));
    return { visible: visibleSet, hidden: hiddenSet };
  }, [tags, filter.activeTagIds, tagFrequency]);

  const closePopover = useCallback(() => setPopoverOpen(false), []);

  useEffect(() => {
    if (!popoverOpen) return undefined;
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') {
        event.preventDefault();
        closePopover();
      }
    };
    const onMouseDown = (event: MouseEvent): void => {
      const popover = popoverRef.current;
      const trigger = overflowButtonRef.current;
      const target = event.target as Node;
      if (popover && popover.contains(target)) return;
      if (trigger && trigger.contains(target)) return;
      closePopover();
    };
    document.addEventListener('keydown', onKey);
    document.addEventListener('mousedown', onMouseDown);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('mousedown', onMouseDown);
    };
  }, [popoverOpen, closePopover]);

  if (tagsQuery.isLoading && tags.length === 0) {
    return (
      <div className="text-xs text-stone-400" data-testid="tag-filter-loading">
        標籤載入中…
      </div>
    );
  }

  const allActive = filter.activeTagIds.size === 0;

  return (
    <div
      role="group"
      aria-label="標籤篩選"
      className="relative flex flex-wrap items-center gap-1.5"
      data-testid="tag-filter-row"
    >
      <button
        type="button"
        aria-pressed={allActive}
        onClick={() => filter.clearAll()}
        className={`rounded-full border px-2 py-0.5 text-xs font-medium transition ${
          allActive
            ? 'border-sky-300 bg-sky-50 text-sky-700'
            : 'border-stone-200 bg-white text-stone-500 hover:bg-stone-100'
        }`}
      >
        全部
      </button>
      {visible.map((tag) => (
        <TagChip
          key={tag.id}
          tag={tag}
          active={filter.activeTagIds.has(tag.id)}
          onToggle={filter.toggleTag}
        />
      ))}
      {hidden.length > 0 && (
        <button
          ref={overflowButtonRef}
          type="button"
          aria-label={`顯示其他 ${hidden.length} 個標籤`}
          aria-haspopup="dialog"
          aria-expanded={popoverOpen}
          data-testid="tag-filter-overflow-trigger"
          onClick={() => setPopoverOpen((v) => !v)}
          className="rounded-full border border-stone-200 bg-white px-2 py-0.5 text-xs font-medium text-stone-500 hover:bg-stone-100"
        >
          <span aria-hidden="true">⋯ {hidden.length}</span>
        </button>
      )}
      {popoverOpen && hidden.length > 0 && (
        <div
          ref={popoverRef}
          role="dialog"
          aria-label="所有標籤"
          data-testid="tag-filter-overflow-popover"
          className="absolute left-0 top-full z-30 mt-1 flex max-h-72 w-64 flex-col gap-2 overflow-y-auto rounded-lg border border-stone-200 bg-white p-2 shadow-lg"
        >
          <div className="flex items-baseline justify-between px-1">
            <span className="text-[11px] font-medium uppercase tracking-wide text-stone-400">
              所有標籤
            </span>
            <button
              type="button"
              onClick={closePopover}
              aria-label="關閉"
              className="rounded-md px-1 text-xs text-stone-400 hover:bg-stone-100 hover:text-stone-700"
            >
              <span aria-hidden="true">✕</span>
            </button>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {tags.map((tag) => (
              <TagChip
                key={tag.id}
                tag={tag}
                active={filter.activeTagIds.has(tag.id)}
                onToggle={filter.toggleTag}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
