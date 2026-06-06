import type { ProsConsItem } from '../api/prosCons';
import type { Timeframe } from '../lib/timeframes';

// Short / mid / long row of clickable chips that anchor-scroll to the
// matching <IndicatorCard> further down the page. The Phase 1 timeframe
// re-layout grouped cards by horizon but the operator still had to
// scroll to find a specific indicator card. This index bar pins the
// 14-indicator overview at the top so any card is one click away.
//
// Each chip carries:
//   * the indicator's signal tone (🟢 / 🔴 / ⚪)
//   * the indicator's display title (passed in from the page)
//   * the indicator's timeframe row colour
//
// Chips with no current pros/cons row (insufficient data) still render
// but are dimmed and not clickable.

export interface IndicatorIndexBarProps {
  items: readonly ProsConsItem[];
  // Display title for the given indicator name (e.g. 'rsi' → 'RSI').
  // Falls back to the indicator_name when missing so a future indicator
  // doesn't get hidden by a stale title map.
  readonly titleFor: (indicatorName: string) => string;
  // Caller-controlled anchor ID resolver — must match the ID used on
  // the corresponding <IndicatorCard> (we keyed those by indicator_name).
  readonly idFor?: (indicatorName: string) => string;
}

const TIMEFRAME_LABEL: Record<Timeframe, string> = {
  short: '短期',
  mid: '中期',
  long: '長期',
};

const TIMEFRAME_ROW_TONE: Record<Timeframe, string> = {
  short: 'bg-sky-50 border-sky-200',
  mid: 'bg-violet-50 border-violet-200',
  long: 'bg-teal-50 border-teal-200',
};

const TIMEFRAME_LABEL_TONE: Record<Timeframe, string> = {
  short: 'text-sky-700',
  mid: 'text-violet-700',
  long: 'text-teal-700',
};

const TONE_DOT: Record<ProsConsItem['tone'], string> = {
  pro: '🟢',
  con: '🔴',
  neutral: '⚪',
};

const DEFAULT_ID = (name: string): string => `indicator-${name}`;

export function IndicatorIndexBar({
  items,
  titleFor,
  idFor = DEFAULT_ID,
}: IndicatorIndexBarProps): JSX.Element {
  // Group by timeframe; preserve the items' ordering within each group.
  const grouped: Record<Timeframe, ProsConsItem[]> = {
    short: [],
    mid: [],
    long: [],
  };
  for (const item of items) {
    grouped[item.timeframe].push(item);
  }

  const rows: Array<{ tf: Timeframe; items: ProsConsItem[] }> = [];
  for (const tf of ['short', 'mid', 'long'] as const) {
    if (grouped[tf].length > 0) rows.push({ tf, items: grouped[tf] });
  }

  if (rows.length === 0) return <></>;

  const handleClick = (indicatorName: string): void => {
    const el = document.getElementById(idFor(indicatorName));
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  };

  return (
    <nav
      aria-label="指標索引"
      data-testid="indicator-index-bar"
      className="flex flex-col gap-1.5"
    >
      {rows.map(({ tf, items: rowItems }) => (
        <div
          key={tf}
          className={`flex flex-wrap items-center gap-1.5 rounded-md border px-2 py-1.5 ${TIMEFRAME_ROW_TONE[tf]}`}
        >
          <span
            className={`inline-flex items-center rounded px-1.5 text-[10px] font-semibold uppercase tracking-wide ${TIMEFRAME_LABEL_TONE[tf]}`}
          >
            {TIMEFRAME_LABEL[tf]}
          </span>
          {rowItems.map((item) => (
            <button
              key={item.indicator_name}
              type="button"
              onClick={() => handleClick(item.indicator_name)}
              className="inline-flex items-center gap-1 rounded-full border border-stone-300 bg-white px-2 py-0.5 text-xs text-stone-700 transition hover:border-stone-400 hover:bg-stone-50"
              aria-label={`跳到 ${titleFor(item.indicator_name)} 卡片`}
            >
              <span aria-hidden="true">{TONE_DOT[item.tone]}</span>
              <span className="font-medium">{titleFor(item.indicator_name)}</span>
            </button>
          ))}
        </div>
      ))}
    </nav>
  );
}
