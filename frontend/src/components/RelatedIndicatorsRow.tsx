import type { ProsConsItem } from '../api/prosCons';

// Compact "what else is firing in the same direction?" row pinned to the
// bottom of each <IndicatorCard>. With 14 indicators on the TickerDetail
// page, the operator's natural question after reading one card is
// "OK, what else confirms / contradicts this?". This row answers that
// without forcing them to scroll through every other card.
//
// Membership rule (deliberately simple):
//   * "同方向" = other indicators IN THE SAME TIMEFRAME with the same
//     pro/con tone. Cross-timeframe confirmation is interesting but
//     adds noise — short-term RSI agreeing with long-term Fed isn't a
//     coincidence operators usually care about.
//   * "反方向" = other indicators IN THE SAME TIMEFRAME with the OPPOSITE
//     pro/con tone (neutrals are not "opposite" — just absent).
//
// Each related indicator gets a small chip with the tone dot + display
// title; clicking it scroll-jumps to that card (same anchor convention
// as IndicatorIndexBar).

export interface RelatedIndicatorsRowProps {
  // The indicator this card represents. Excluded from the related list.
  readonly currentName: string;
  // All pros/cons items for the current ticker. Used to compute related
  // membership; small array (≤ 14 entries) so no memoisation needed.
  readonly items: readonly ProsConsItem[];
  readonly titleFor: (indicatorName: string) => string;
  readonly idFor?: (indicatorName: string) => string;
}

const DEFAULT_ID = (name: string): string => `indicator-${name}`;

const TONE_DOT: Record<ProsConsItem['tone'], string> = {
  pro: '🟢',
  con: '🔴',
  neutral: '⚪',
};

export function RelatedIndicatorsRow({
  currentName,
  items,
  titleFor,
  idFor = DEFAULT_ID,
}: RelatedIndicatorsRowProps): JSX.Element | null {
  const current = items.find((it) => it.indicator_name === currentName);
  if (!current) return null;
  if (current.tone === 'neutral') {
    // Neutral indicator → no meaningful confirmation / contradiction to
    // surface. Skip the row entirely rather than confuse the operator
    // with "0 同方向 / 0 反方向".
    return null;
  }

  const sameTimeframe = items.filter(
    (it) => it.timeframe === current.timeframe && it.indicator_name !== currentName,
  );
  const aligned = sameTimeframe.filter((it) => it.tone === current.tone);
  const opposite = sameTimeframe.filter(
    (it) => it.tone !== current.tone && it.tone !== 'neutral',
  );

  if (aligned.length === 0 && opposite.length === 0) return null;

  const handleClick = (name: string): void => {
    const el = document.getElementById(idFor(name));
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  return (
    <footer
      data-testid="related-indicators-row"
      className="flex flex-col gap-1 border-t border-stone-100 pt-2 text-xs text-stone-600"
    >
      {aligned.length > 0 && (
        <RelatedGroup
          label={`同方向 ${aligned.length}`}
          ariaLabel={`同方向訊號:${aligned.length} 個`}
          items={aligned}
          titleFor={titleFor}
          onClick={handleClick}
        />
      )}
      {opposite.length > 0 && (
        <RelatedGroup
          label={`反方向 ${opposite.length}`}
          ariaLabel={`反方向訊號:${opposite.length} 個`}
          items={opposite}
          titleFor={titleFor}
          onClick={handleClick}
        />
      )}
    </footer>
  );
}

interface RelatedGroupProps {
  label: string;
  ariaLabel: string;
  items: readonly ProsConsItem[];
  titleFor: (indicatorName: string) => string;
  onClick: (indicatorName: string) => void;
}

function RelatedGroup({
  label,
  ariaLabel,
  items,
  titleFor,
  onClick,
}: RelatedGroupProps): JSX.Element {
  return (
    <div aria-label={ariaLabel} className="flex flex-wrap items-center gap-1.5">
      <span className="text-stone-500">{label}:</span>
      {items.map((it) => (
        <button
          key={it.indicator_name}
          type="button"
          onClick={() => onClick(it.indicator_name)}
          className="inline-flex items-center gap-1 rounded-full border border-stone-200 bg-stone-50 px-2 py-0.5 text-[11px] text-stone-700 transition hover:border-stone-300 hover:bg-stone-100"
        >
          <span aria-hidden="true">{TONE_DOT[it.tone]}</span>
          <span>{titleFor(it.indicator_name)}</span>
        </button>
      ))}
    </div>
  );
}
