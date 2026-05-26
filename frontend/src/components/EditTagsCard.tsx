import { useMemo, useRef, useState, useEffect, useCallback } from 'react';
import {
  useAttachTag,
  useCreateWatchlistTag,
  useDetachTag,
  useWatchlistTags,
} from '../hooks/useWatchlistTags';
import {
  useMoveSymbolToGroup,
  useWatchlistGroups,
} from '../hooks/useWatchlistGroups';
import type { WatchlistItem } from '../api/watchlist';
import type { WatchlistTag } from '../api/watchlistTags';

interface EditTagsCardProps {
  item: WatchlistItem;
  onClose: () => void;
  // Where to anchor the floating card relative to the page. The sidebar
  // row's "..." menu measures the menu button position and passes it in;
  // the card clamps itself inside the viewport.
  anchor: { top: number; left: number } | null;
}

// 8-colour palette for new-tag creation. Chosen for distinguishability on
// the stone-50 background. Tag colours flow through to the chip background
// (with alpha) and border (full).
const NEW_TAG_PALETTE: readonly string[] = [
  '#0ea5e9', // sky
  '#10b981', // emerald
  '#f59e0b', // amber
  '#ef4444', // rose-ish
  '#8b5cf6', // violet
  '#ec4899', // pink
  '#14b8a6', // teal
  '#737373', // neutral
];

// Popover-style edit card. Renders fixed-positioned next to the row's "..."
// menu so the operator can tweak tags without leaving the sidebar. Escape /
// outside-click close. No full Modal portal because we want sidebar context
// to remain visible behind the card.
export function EditTagsCard({ item, onClose, anchor }: EditTagsCardProps): JSX.Element {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [tagInput, setTagInput] = useState<string>('');
  const tagsQuery = useWatchlistTags();
  const groupsQuery = useWatchlistGroups();
  const attach = useAttachTag();
  const detach = useDetachTag();
  const create = useCreateWatchlistTag();
  const moveGroup = useMoveSymbolToGroup();

  // Tags currently on the symbol — read from the watchlist row (already
  // hydrated by useWatchlist).
  const attachedTagIds = useMemo(
    () => new Set(item.tags.map((t) => t.id)),
    [item.tags],
  );

  const availableTags = useMemo(
    () => (tagsQuery.data?.data ?? []).filter((t) => !attachedTagIds.has(t.id)),
    [tagsQuery.data, attachedTagIds],
  );

  // Autocomplete suggestions: substring match against the typed text. Empty
  // input shows nothing (the popular chips below cover discovery).
  const suggestions = useMemo<readonly WatchlistTag[]>(() => {
    const q = tagInput.trim().toLowerCase();
    if (!q) return [];
    return availableTags
      .filter((t) => t.name.toLowerCase().includes(q))
      .slice(0, 6);
  }, [tagInput, availableTags]);

  const popularTags = useMemo(
    () =>
      (tagsQuery.data?.popular ?? []).filter(
        (t) => !attachedTagIds.has(t.id),
      ),
    [tagsQuery.data, attachedTagIds],
  );

  const handleClose = useCallback(() => {
    onClose();
  }, [onClose]);

  useEffect(() => {
    inputRef.current?.focus();
    const onKeydown = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') {
        event.preventDefault();
        handleClose();
      }
    };
    const onMouseDown = (event: MouseEvent): void => {
      const container = containerRef.current;
      if (!container) return;
      if (!container.contains(event.target as Node)) handleClose();
    };
    document.addEventListener('keydown', onKeydown);
    document.addEventListener('mousedown', onMouseDown);
    return () => {
      document.removeEventListener('keydown', onKeydown);
      document.removeEventListener('mousedown', onMouseDown);
    };
  }, [handleClose]);

  const handleAttachByName = async (name: string): Promise<void> => {
    const trimmed = name.trim();
    if (!trimmed) return;
    // Reuse existing tag if it matches case-insensitively; otherwise create.
    const existing = availableTags.find(
      (t) => t.name.toLowerCase() === trimmed.toLowerCase(),
    );
    try {
      if (existing) {
        await attach.mutateAsync({ symbol: item.symbol, tagId: existing.id });
      } else {
        // Pick a deterministic colour from the palette using the name hash so
        // re-creating the same tag name twice gives the same colour.
        const idx = Math.abs(trimmed.split('').reduce((acc, c) => acc + c.charCodeAt(0), 0)) %
          NEW_TAG_PALETTE.length;
        const color = NEW_TAG_PALETTE[idx] ?? '#737373';
        const created = await create.mutateAsync({ name: trimmed, color });
        await attach.mutateAsync({ symbol: item.symbol, tagId: created.id });
      }
      setTagInput('');
    } catch (err) {
      // Errors bubble up via TanStack Query state; keep UI quiet here so
      // the operator can simply retry.
      console.error('attach tag failed', err);
    }
  };

  const handleInputKey = (event: React.KeyboardEvent<HTMLInputElement>): void => {
    if (event.key === 'Enter') {
      event.preventDefault();
      void handleAttachByName(tagInput);
    }
  };

  // Edge-clamp the popover so it never overflows the viewport on small
  // screens. Width fixed at 280px so the chips wrap predictably.
  const POPOVER_WIDTH = 280;
  const top = anchor ? Math.max(8, Math.min(anchor.top, window.innerHeight - 320)) : 80;
  const left = anchor ? Math.max(8, Math.min(anchor.left, window.innerWidth - POPOVER_WIDTH - 8)) : 80;

  return (
    <div
      ref={containerRef}
      role="dialog"
      aria-label={`編輯 ${item.symbol} 的群組與標籤`}
      data-testid="edit-tags-card"
      className="fixed z-50 flex flex-col gap-3 rounded-xl border border-stone-200 bg-white p-3 shadow-xl"
      style={{ top, left, width: POPOVER_WIDTH }}
    >
      <header className="flex items-baseline justify-between gap-2">
        <span className="font-mono text-sm font-semibold text-stone-900">
          {item.symbol}
        </span>
        <button
          type="button"
          aria-label="關閉"
          onClick={handleClose}
          className="rounded-md px-1.5 py-0.5 text-xs text-stone-500 hover:bg-stone-100 hover:text-stone-900"
        >
          <span aria-hidden="true">✕</span>
        </button>
      </header>

      <div className="flex flex-col gap-1">
        <label
          htmlFor={`group-select-${item.symbol}`}
          className="text-xs font-medium text-stone-600"
        >
          群組
        </label>
        <select
          id={`group-select-${item.symbol}`}
          value={item.groupId ?? ''}
          onChange={(e) => {
            const raw = e.target.value;
            const next = raw === '' ? null : Number.parseInt(raw, 10);
            void moveGroup.mutateAsync({ symbol: item.symbol, groupId: next });
          }}
          className="rounded-md border border-stone-300 bg-white px-2 py-1 text-sm text-stone-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-500"
        >
          <option value="">未分類</option>
          {(groupsQuery.data?.data ?? []).map((g) => (
            <option key={g.id} value={g.id}>
              {g.name}
            </option>
          ))}
        </select>
      </div>

      <div className="flex flex-col gap-1.5">
        <span className="text-xs font-medium text-stone-600">標籤</span>
        <div className="flex flex-wrap gap-1.5">
          {item.tags.length === 0 && (
            <span className="text-xs text-stone-400">尚未加入標籤</span>
          )}
          {item.tags.map((tag) => (
            <button
              key={tag.id}
              type="button"
              onClick={() =>
                void detach.mutateAsync({ symbol: item.symbol, tagId: tag.id })
              }
              className="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs"
              style={{
                borderColor: tag.color,
                backgroundColor: `${tag.color}22`,
                color: tag.color,
              }}
              aria-label={`移除標籤 ${tag.name}`}
            >
              <span>{tag.name}</span>
              <span aria-hidden="true">×</span>
            </button>
          ))}
        </div>

        <input
          ref={inputRef}
          type="text"
          value={tagInput}
          onChange={(e) => setTagInput(e.target.value)}
          onKeyDown={handleInputKey}
          placeholder="輸入標籤名稱後按 Enter"
          aria-label="新增標籤"
          className="rounded-md border border-stone-300 bg-white px-2 py-1 text-sm text-stone-900 placeholder:text-stone-400 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-500"
        />

        {suggestions.length > 0 && (
          <ul className="flex flex-wrap gap-1.5" aria-label="自動完成建議">
            {suggestions.map((tag) => (
              <li key={tag.id}>
                <button
                  type="button"
                  onClick={() =>
                    void attach
                      .mutateAsync({ symbol: item.symbol, tagId: tag.id })
                      .then(() => setTagInput(''))
                  }
                  className="rounded-full border px-2 py-0.5 text-xs"
                  style={{
                    borderColor: tag.color,
                    color: tag.color,
                  }}
                >
                  + {tag.name}
                </button>
              </li>
            ))}
          </ul>
        )}

        {popularTags.length > 0 && (
          <div className="flex flex-col gap-1">
            <span className="text-[11px] text-stone-400">常用</span>
            <ul className="flex flex-wrap gap-1.5" aria-label="常用標籤建議">
              {popularTags.slice(0, 6).map((tag) => (
                <li key={tag.id}>
                  <button
                    type="button"
                    onClick={() =>
                      void attach.mutateAsync({ symbol: item.symbol, tagId: tag.id })
                    }
                    className="rounded-full border px-2 py-0.5 text-xs"
                    style={{
                      borderColor: tag.color,
                      color: tag.color,
                    }}
                  >
                    + {tag.name}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}
