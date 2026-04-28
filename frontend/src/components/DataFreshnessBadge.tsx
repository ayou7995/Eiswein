import type { DataFreshness } from '../api/settings';
import { Tooltip } from './Tooltip';

interface DataFreshnessBadgeProps {
  freshness: DataFreshness;
}

// Format `2026-04-14T16:00:00-04:00` → `16:00 ET` for display. We rely on
// the backend providing an ET-localised ISO string; trimming after the
// "T" and before timezone offset gives us the wall-clock part that the
// user actually cares about.
function formatEtClock(iso: string | null): string {
  if (!iso) return '';
  const t = iso.split('T')[1];
  if (!t) return '';
  const hhmm = t.slice(0, 5);
  return `${hhmm} ET`;
}

function minutesUntil(iso: string | null): number | null {
  if (!iso) return null;
  const target = Date.parse(iso);
  if (Number.isNaN(target)) return null;
  const diffMs = target - Date.now();
  if (diffMs <= 0) return 0;
  return Math.round(diffMs / 60000);
}

export function DataFreshnessBadge({
  freshness,
}: DataFreshnessBadgeProps): JSX.Element {
  if (!freshness.is_trading_day_today) {
    return (
      <span
        role="status"
        data-testid="data-freshness-badge"
        aria-label="今日非交易日"
        className="inline-flex items-center gap-1 rounded-full border border-slate-500/40 bg-slate-500/10 px-2 py-0.5 text-xs font-medium text-slate-400"
      >
        休市
      </span>
    );
  }

  if (freshness.is_intraday_partial) {
    const closeClock = formatEtClock(freshness.market_close_at);
    const minsLeft = minutesUntil(freshness.market_close_at);
    const tooltip =
      minsLeft !== null && minsLeft > 0
        ? `今日尚未收盤,訊號可能與最終值不同。距離收盤約 ${minsLeft} 分鐘 (${closeClock})。`
        : '今日尚未收盤,訊號可能與最終值不同。';
    return (
      <Tooltip text={tooltip}>
        <span
          role="status"
          data-testid="data-freshness-badge"
          aria-label={tooltip}
          className="inline-flex items-center gap-1 rounded-full border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-xs font-medium text-amber-300"
        >
          盤中即時
        </span>
      </Tooltip>
    );
  }

  // Settled: today is a trading day AND the latest written bar is past
  // close+buffer. Show the close clock as confirmation.
  const closeClock = formatEtClock(freshness.market_close_at);
  return (
    <span
      role="status"
      data-testid="data-freshness-badge"
      aria-label={`已收盤 ${closeClock}`}
      className="inline-flex items-center gap-1 rounded-full border border-signal-green/40 bg-signal-green/10 px-2 py-0.5 text-xs font-medium text-signal-green"
    >
      已收盤{closeClock ? ` ${closeClock}` : ''}
    </span>
  );
}
