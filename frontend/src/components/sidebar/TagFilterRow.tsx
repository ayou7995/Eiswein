import { useWatchlistTags } from '../../hooks/useWatchlistTags';
import type { SidebarFilterState } from '../../hooks/useSidebarFilter';

interface TagFilterRowProps {
  filter: SidebarFilterState;
}

// Multi-select chip row: 全部 + each tag. "全部" is the always-pressed sentinel
// that clears all active selections. Each tag chip toggles its own membership.
// State lives in useSidebarFilter so the SidebarWatchlist consuming it stays
// in sync.
export function TagFilterRow({ filter }: TagFilterRowProps): JSX.Element {
  const { data, isLoading } = useWatchlistTags();
  const tags = data?.data ?? [];

  if (isLoading && tags.length === 0) {
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
      className="flex flex-wrap items-center gap-1.5"
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
      {tags.map((tag) => {
        const active = filter.activeTagIds.has(tag.id);
        return (
          <button
            key={tag.id}
            type="button"
            aria-pressed={active}
            onClick={() => filter.toggleTag(tag.id)}
            className={`rounded-full border px-2 py-0.5 text-xs font-medium transition ${
              active
                ? 'border-stone-400 bg-stone-200 text-stone-900'
                : 'border-stone-200 bg-white text-stone-600 hover:bg-stone-100'
            }`}
            style={
              active
                ? { borderColor: tag.color, backgroundColor: `${tag.color}22`, color: tag.color }
                : undefined
            }
          >
            {tag.name}
          </button>
        );
      })}
    </div>
  );
}
