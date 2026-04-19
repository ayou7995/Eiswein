import type { DataStatus } from '../api/watchlist';

interface DataStatusBadgeProps {
  status: DataStatus;
}

const CONFIG: Record<DataStatus, { label: string; className: string; ariaLabel: string }> = {
  pending: {
    label: '載入中',
    className: 'border-amber-500/40 bg-amber-500/10 text-amber-300',
    ariaLabel: '資料載入中',
  },
  ready: {
    label: '已就緒',
    className: 'border-signal-green/40 bg-signal-green/10 text-signal-green',
    ariaLabel: '資料已就緒',
  },
  failed: {
    label: '失敗',
    className: 'border-signal-red/40 bg-signal-red/10 text-signal-red',
    ariaLabel: '資料載入失敗',
  },
  delisted: {
    label: '已下市',
    className: 'border-slate-500/40 bg-slate-500/10 text-slate-400',
    ariaLabel: '已下市或無效',
  },
};

export function DataStatusBadge({ status }: DataStatusBadgeProps): JSX.Element {
  const cfg = CONFIG[status];
  return (
    <span
      role="status"
      aria-label={cfg.ariaLabel}
      className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium ${cfg.className}`}
    >
      {cfg.label}
    </span>
  );
}
