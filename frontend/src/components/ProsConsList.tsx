import type { ProsConsItem, ProsConsTone } from '../api/prosCons';
import { TIMEFRAME_STYLE } from '../lib/timeframes';

// Scannable Pros/Cons UI — NOT a narrator. Each item renders verbatim from
// the backend (`short_label`) with the raw detail available behind an
// expand-on-tap `<details>` element.
const TONE_DOT: Record<ProsConsTone, { emoji: string; ariaLabel: string }> = {
  pro: { emoji: '🟢', ariaLabel: '利多訊號' },
  con: { emoji: '🔴', ariaLabel: '利空訊號' },
  neutral: { emoji: '⚪', ariaLabel: '中性或資料不足' },
};

function humanizeKey(key: string): string {
  return key.replace(/_/g, ' ');
}

function renderValue(value: unknown): string {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'boolean') return value ? '是' : '否';
  if (typeof value === 'number') {
    // Keep 4 significant digits for small floats, integer otherwise.
    if (Number.isInteger(value)) return String(value);
    return Number.parseFloat(value.toFixed(4)).toString();
  }
  if (typeof value === 'string') return value;
  return JSON.stringify(value);
}

export interface ProsConsListProps {
  items: readonly ProsConsItem[];
  emptyMessage?: string;
  // When true, neutral items collapse into a single "⚪ 中性訊號 (N)" group
  // that reveals them on toggle. Enabled by default for the per-ticker
  // pros/cons card where the list has up to 8 items.
  collapseNeutrals?: boolean;
}

export function ProsConsList({
  items,
  emptyMessage = '資料不足以判斷',
  collapseNeutrals = true,
}: ProsConsListProps): JSX.Element {
  if (items.length === 0) {
    return (
      <p role="status" className="text-sm text-slate-400">
        {emptyMessage}
      </p>
    );
  }

  const nonNeutral = collapseNeutrals
    ? items.filter((item) => item.tone !== 'neutral')
    : items;
  const neutrals = collapseNeutrals
    ? items.filter((item) => item.tone === 'neutral')
    : [];

  return (
    <div className="flex flex-col gap-2">
      <ul className="flex flex-col divide-y divide-slate-800 overflow-hidden rounded-md border border-slate-800">
        {nonNeutral.map((item) => (
          <ProsConsRow key={`${item.indicator_name}-${item.tone}`} item={item} />
        ))}
        {!collapseNeutrals && nonNeutral.length === 0 && (
          <li className="bg-slate-900/40 px-3 py-2 text-sm text-slate-400">
            {emptyMessage}
          </li>
        )}
      </ul>
      {collapseNeutrals && neutrals.length > 0 && (
        <details className="rounded-md border border-slate-800 bg-slate-900/40">
          <summary
            data-testid="neutral-summary"
            className="cursor-pointer px-3 py-2 text-sm text-slate-300 hover:text-slate-100"
          >
            ⚪ 中性訊號 ({neutrals.length})
          </summary>
          <ul className="flex flex-col divide-y divide-slate-800 border-t border-slate-800">
            {neutrals.map((item) => (
              <ProsConsRow key={`${item.indicator_name}-neutral`} item={item} />
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

interface ProsConsRowProps {
  item: ProsConsItem;
}

function ProsConsRow({ item }: ProsConsRowProps): JSX.Element {
  const tone = TONE_DOT[item.tone];
  const tf = TIMEFRAME_STYLE[item.timeframe];
  const detailEntries = Object.entries(item.detail);
  return (
    <li className="bg-slate-900/40">
      <details>
        <summary
          data-testid="pros-cons-summary"
          className="flex cursor-pointer items-center gap-2 px-3 py-2 text-sm text-slate-200 hover:text-white"
        >
          <span aria-label={tone.ariaLabel}>{tone.emoji}</span>
          <span className="flex-1">{item.short_label}</span>
          <span
            data-testid="timeframe-chip"
            aria-label={tf.ariaLabel}
            className={`inline-flex items-center rounded-full border px-1.5 py-0.5 text-[10px] font-medium leading-none ${tf.className}`}
          >
            {tf.label}
          </span>
          {detailEntries.length > 0 && (
            <span aria-hidden="true" className="text-xs text-slate-500">
              詳細
            </span>
          )}
        </summary>
        {detailEntries.length > 0 && (
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 border-t border-slate-800 bg-slate-950/40 px-3 py-2 text-xs text-slate-300">
            {detailEntries.map(([key, value]) => (
              <div key={key} className="contents">
                <dt className="font-mono text-slate-500">{humanizeKey(key)}</dt>
                <dd className="font-mono text-slate-200">{renderValue(value)}</dd>
              </div>
            ))}
          </dl>
        )}
      </details>
    </li>
  );
}
