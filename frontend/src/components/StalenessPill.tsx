import { Explainable } from './Explainable';

// "資料截至 X" pill — surfaces the gap between what date this indicator
// claims to represent (the snapshot's trade_date) and the date of the
// actual data the indicator was computed against.
//
// Why this exists: indicators read whatever the latest value of their
// input frame is. When FRED hasn't published today's VIX yet, the
// indicator carry-forwards yesterday's value but the snapshot still
// dates to today. Without this pill, the operator sees "VIX 15.4" on
// the 6/6 dashboard and reasonably believes that's the 6/6 close —
// when in fact it's the 6/4 close because FRED is behind.
//
// Renders nothing when:
//   - data_as_of is null/undefined (legacy rows from before the field
//     existed; no honest answer to give)
//   - data_as_of >= snapshotDate (data is current — the common case)
//
// The pill is intentionally muted (amber, small, secondary) — it's a
// caveat, not a warning. The signal itself is still meaningful; the
// pill just tells the operator "this is yesterday's reading."

export interface StalenessPillProps {
  // The actual date of the underlying data (YYYY-MM-DD or Date). Backend
  // emits ISO date strings; the component normalises.
  readonly dataAsOf: string | null | undefined;
  // The snapshot date — what the indicator is dated AS. Pill fires when
  // dataAsOf < snapshotDate.
  readonly snapshotDate: string;
}

function parseIso(value: string): Date | null {
  // YYYY-MM-DD only — we anchor to UTC so timezone-agnostic comparison
  // works regardless of where the operator is.
  if (!/^\d{4}-\d{2}-\d{2}/.test(value)) return null;
  const ts = Date.UTC(
    Number.parseInt(value.slice(0, 4), 10),
    Number.parseInt(value.slice(5, 7), 10) - 1,
    Number.parseInt(value.slice(8, 10), 10),
  );
  return Number.isNaN(ts) ? null : new Date(ts);
}

function daysBetween(earlier: Date, later: Date): number {
  return Math.round((later.getTime() - earlier.getTime()) / (24 * 60 * 60 * 1000));
}

function formatMonthDay(value: string): string {
  // 2026-06-04 → 6/4. The full year is implicit on a daily dashboard and
  // the operator parses 月/日 faster than 2026-06-04.
  if (!/^\d{4}-\d{2}-\d{2}/.test(value)) return value;
  const month = Number.parseInt(value.slice(5, 7), 10);
  const day = Number.parseInt(value.slice(8, 10), 10);
  return `${month}/${day}`;
}

export function StalenessPill({
  dataAsOf,
  snapshotDate,
}: StalenessPillProps): JSX.Element | null {
  if (!dataAsOf) return null;
  const dataDate = parseIso(dataAsOf);
  const snapDate = parseIso(snapshotDate);
  if (!dataDate || !snapDate) return null;
  if (dataDate.getTime() >= snapDate.getTime()) return null;

  const gapDays = daysBetween(dataDate, snapDate);
  const label = `資料截至 ${formatMonthDay(dataAsOf)}`;
  const tooltip = `指標的原始資料來源 (FRED / yfinance / 廣度) 截至 ${dataAsOf},比快照日期 ${snapshotDate} 落後 ${gapDays} 天。常見原因:FRED 對 VIX 等日資料是 T+1 發布;對 DTWEXBGS 是週發布;對 FEDFUNDS 是月發布。今天看到的數字實際上是 ${dataAsOf} 的收盤值。`;

  return (
    <Explainable title="資料新鮮度" explanation={<p>{tooltip}</p>}>
      <span
        data-testid="staleness-pill"
        aria-label={tooltip}
        className="inline-flex items-center gap-1 rounded-full border border-amber-300 bg-amber-50 px-2 py-0.5 text-[11px] font-medium text-amber-700"
      >
        <span aria-hidden="true">⏳</span>
        {label}
      </span>
    </Explainable>
  );
}
