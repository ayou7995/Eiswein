import { useLocation } from 'react-router-dom';
import { useMarketPosture } from '../hooks/useMarketPosture';
import { useSystemInfo } from '../hooks/useSettings';
import { DataFreshnessBadge } from '../components/DataFreshnessBadge';
import { ROUTES } from '../lib/constants';

// Sidebar status card — two-row summary of market posture, tinted to match
// the posture (offensive / normal / defensive).
//
//   ┌──────────────────────────────────────────────────────────────┐
//   │ ● 進攻                                              34 天    │  ← text-sm bold
//   │ 買 3 · 持 1 · 賣 0                  [已收盤 16:00 ET]        │  ← text-xs
//   └──────────────────────────────────────────────────────────────┘
//
// The pill is suppressed entirely on MarketOverview (the page hero already
// renders this information at a larger size and on the right side of the
// page header — keeping the sidebar copy alongside would surface the same
// posture / streak / counts / freshness in three places at once).
// On every other page the sidebar pill is the only place market posture
// surfaces, so we keep it visible there.

const POSTURE_TINT: Record<string, { bg: string; border: string; text: string; dot: string }> = {
  offensive: {
    bg: 'bg-emerald-50',
    border: 'border-emerald-200',
    text: 'text-emerald-800',
    dot: 'bg-emerald-500',
  },
  normal: {
    bg: 'bg-amber-50',
    border: 'border-amber-200',
    text: 'text-amber-800',
    dot: 'bg-amber-500',
  },
  defensive: {
    bg: 'bg-rose-50',
    border: 'border-rose-200',
    text: 'text-rose-800',
    dot: 'bg-rose-500',
  },
};

const NEUTRAL_TINT = {
  bg: 'bg-stone-50',
  border: 'border-stone-200',
  text: 'text-stone-700',
  dot: 'bg-stone-400',
};

export function SidebarStatusCard(): JSX.Element | null {
  const { pathname } = useLocation();
  const { data: posture, isLoading } = useMarketPosture();
  const { data: sysInfo } = useSystemInfo();

  // MarketOverview hero already shows posture + streak + counts +
  // freshness at full size; rendering the sidebar pill alongside would
  // surface the same data three places at once.
  if (pathname === ROUTES.DASHBOARD) return null;

  if (isLoading) {
    return (
      <div
        data-testid="sidebar-status-card-loading"
        className="rounded-md border border-stone-200 bg-stone-50 px-2 py-1.5 text-xs text-stone-500"
      >
        市場態勢載入中…
      </div>
    );
  }

  if (!posture) {
    return (
      <div
        data-testid="sidebar-status-card-empty"
        className="rounded-md border border-stone-200 bg-stone-50 px-2 py-1.5 text-xs text-stone-500"
      >
        等待首次運算
      </div>
    );
  }

  const tint = POSTURE_TINT[posture.posture] ?? NEUTRAL_TINT;

  return (
    <section
      aria-label="市場態勢摘要"
      data-testid="sidebar-status-card"
      className={`flex flex-col gap-1 rounded-md border px-2.5 py-1.5 ${tint.bg} ${tint.border}`}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5">
          <span
            aria-hidden="true"
            className={`inline-block h-2 w-2 shrink-0 rounded-full ${tint.dot}`}
          />
          <span className={`text-sm font-semibold ${tint.text}`}>
            {posture.posture_label}
          </span>
        </div>
        <span
          className="text-xs text-stone-500"
          aria-label={`已持續 ${posture.streak_days} 天`}
        >
          {posture.streak_days} 天
        </span>
      </div>
      <div className="flex items-center justify-between gap-2">
        <span
          className="font-mono text-xs tabular-nums text-stone-700"
          aria-label={`綠燈 ${posture.regime_green_count}、黃燈 ${posture.regime_yellow_count}、紅燈 ${posture.regime_red_count}`}
        >
          買 {posture.regime_green_count}
          <span className="mx-1 text-stone-300" aria-hidden="true">·</span>
          持 {posture.regime_yellow_count}
          <span className="mx-1 text-stone-300" aria-hidden="true">·</span>
          賣 {posture.regime_red_count}
        </span>
        {sysInfo?.data_freshness && (
          <div className="shrink-0">
            <DataFreshnessBadge freshness={sysInfo.data_freshness} />
          </div>
        )}
      </div>
    </section>
  );
}
