import { useMarketPosture } from '../hooks/useMarketPosture';
import { useSystemInfo } from '../hooks/useSettings';
import { DataFreshnessBadge } from '../components/DataFreshnessBadge';

// Sidebar status card — compact summary of market posture (label + streak
// days + green/yellow/red regime vote counts). Same backend data the
// market-overview page uses; this card is the always-visible micro-version.
//
// Render rules:
//   - Loading / 404 / error: collapse to a single grey strip. The
//     market-overview page handles the loud "等待首次運算" message.
//   - Pale-emerald background when posture is offensive, pale-amber for
//     normal, pale-rose for defensive — same tone family as the regime
//     SignalBadge so the operator's colour intuition transfers across views.

const POSTURE_TINT: Record<string, string> = {
  offensive: 'bg-emerald-50 border-emerald-200 text-emerald-900',
  normal: 'bg-amber-50 border-amber-200 text-amber-900',
  defensive: 'bg-rose-50 border-rose-200 text-rose-900',
};

export function SidebarStatusCard(): JSX.Element {
  const { data: posture, isLoading } = useMarketPosture();
  const { data: sysInfo } = useSystemInfo();

  if (isLoading) {
    return (
      <div
        data-testid="sidebar-status-card-loading"
        className="rounded-xl border border-stone-200 bg-stone-100 px-3 py-2 text-xs text-stone-500"
      >
        市場態勢載入中…
      </div>
    );
  }

  if (!posture) {
    return (
      <div
        data-testid="sidebar-status-card-empty"
        className="rounded-xl border border-stone-200 bg-stone-100 px-3 py-2 text-xs text-stone-500"
      >
        等待首次運算
      </div>
    );
  }

  const tint = POSTURE_TINT[posture.posture] ?? 'bg-stone-100 border-stone-200 text-stone-700';

  return (
    <section
      aria-label="市場態勢摘要"
      data-testid="sidebar-status-card"
      className={`flex flex-col gap-1 rounded-xl border px-3 py-2 ${tint}`}
    >
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-base font-semibold">{posture.posture_label}</span>
        <span className="text-xs opacity-80">{posture.streak_days} 天</span>
      </div>
      <div className="flex items-center gap-3 text-xs font-mono tabular-nums">
        <span>買 {posture.regime_green_count}</span>
        <span>持 {posture.regime_yellow_count}</span>
        <span>賣 {posture.regime_red_count}</span>
      </div>
      {sysInfo?.data_freshness && (
        <div className="mt-1">
          <DataFreshnessBadge freshness={sysInfo.data_freshness} />
        </div>
      )}
    </section>
  );
}
