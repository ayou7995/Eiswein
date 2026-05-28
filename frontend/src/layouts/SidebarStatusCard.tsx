import { useMarketPosture } from '../hooks/useMarketPosture';
import { useSystemInfo } from '../hooks/useSettings';
import { DataFreshnessBadge } from '../components/DataFreshnessBadge';

// Sidebar status card — single-row summary of market posture. Pre-redesign
// this took three rows; the slim version condenses everything onto one
// 28-32px row so the sidebar shows more tickers without scrolling.
//
// Layout:
//   [● 進攻 · 34d · 3/1/0]                       [已收盤 16:00 ET]
//   |---- left: posture group ----|   |--- right: freshness badge ---|
//
// The colored dot replaces the chunky tinted card background — same
// posture-→-color mapping, much lower visual weight. Counts collapse to
// "G/Y/R" tabular nums so they line up regardless of digit width.

const POSTURE_DOT: Record<string, string> = {
  offensive: 'bg-emerald-500',
  normal: 'bg-amber-500',
  defensive: 'bg-rose-500',
};

const POSTURE_TEXT: Record<string, string> = {
  offensive: 'text-emerald-700',
  normal: 'text-amber-700',
  defensive: 'text-rose-700',
};

export function SidebarStatusCard(): JSX.Element {
  const { data: posture, isLoading } = useMarketPosture();
  const { data: sysInfo } = useSystemInfo();

  if (isLoading) {
    return (
      <div
        data-testid="sidebar-status-card-loading"
        className="flex items-center gap-2 rounded-md border border-stone-200 bg-stone-50 px-2 py-1 text-xs text-stone-500"
      >
        <span className="inline-block h-2 w-2 shrink-0 animate-pulse rounded-full bg-stone-300" />
        <span>市場態勢載入中…</span>
      </div>
    );
  }

  if (!posture) {
    return (
      <div
        data-testid="sidebar-status-card-empty"
        className="flex items-center gap-2 rounded-md border border-stone-200 bg-stone-50 px-2 py-1 text-xs text-stone-500"
      >
        <span className="inline-block h-2 w-2 shrink-0 rounded-full bg-stone-300" />
        <span>等待首次運算</span>
      </div>
    );
  }

  const dot = POSTURE_DOT[posture.posture] ?? 'bg-stone-400';
  const textColor = POSTURE_TEXT[posture.posture] ?? 'text-stone-700';

  return (
    <section
      aria-label="市場態勢摘要"
      data-testid="sidebar-status-card"
      className="flex items-center gap-2 rounded-md border border-stone-200 bg-white px-2 py-1 text-xs"
    >
      <span
        aria-hidden="true"
        className={`inline-block h-2 w-2 shrink-0 rounded-full ${dot}`}
      />
      <span className={`font-semibold ${textColor}`}>{posture.posture_label}</span>
      <span className="text-stone-400" aria-hidden="true">·</span>
      <span className="text-stone-600" aria-label={`已持續 ${posture.streak_days} 天`}>
        {posture.streak_days}d
      </span>
      <span className="text-stone-400" aria-hidden="true">·</span>
      <span
        className="font-mono tabular-nums text-stone-700"
        aria-label={`綠燈 ${posture.regime_green_count}、黃燈 ${posture.regime_yellow_count}、紅燈 ${posture.regime_red_count}`}
      >
        {posture.regime_green_count}/{posture.regime_yellow_count}/{posture.regime_red_count}
      </span>
      {sysInfo?.data_freshness && (
        <div className="ml-auto shrink-0">
          <DataFreshnessBadge freshness={sysInfo.data_freshness} />
        </div>
      )}
    </section>
  );
}
