import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { LoadingSpinner } from './LoadingSpinner';
import { TradeLogTable } from './TradeLogTable';
import { usePosition } from '../hooks/usePositions';
import { parseDecimalString } from '../api/tickerSignal';
import type { PositionResponse } from '../api/positions';
import { ROUTES } from '../lib/constants';

export type PositionsSortKey = 'market_value' | 'unrealized_pnl' | 'shares';
export type PositionsSortDir = 'asc' | 'desc';

export interface PositionsTableProps {
  positions: readonly PositionResponse[];
  expandedId: number | null;
  onToggle: (id: number) => void;
  onAdd: (p: PositionResponse) => void;
  onReduce: (p: PositionResponse) => void;
  onClose: (p: PositionResponse) => void;
}

interface PositionRowMetrics {
  position: PositionResponse;
  marketValue: number | null;
  unrealizedPnl: number | null;
  unrealizedPct: number | null;
  shares: number | null;
  avgCost: number | null;
  currentPrice: number | null;
  allocationPct: number | null;
  isClosed: boolean;
}

const CURRENCY_FORMATTER = new Intl.NumberFormat('en-US', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const PERCENT_FORMATTER = new Intl.NumberFormat('en-US', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

function formatCurrency(value: number | null): string {
  if (value == null) return '—';
  return CURRENCY_FORMATTER.format(value);
}

function formatSignedCurrency(value: number | null): string {
  if (value == null) return '—';
  const sign = value > 0 ? '+' : '';
  return `${sign}${CURRENCY_FORMATTER.format(value)}`;
}

function formatPercent(value: number | null, signed = false): string {
  if (value == null) return '';
  const sign = signed && value > 0 ? '+' : '';
  return `${sign}${PERCENT_FORMATTER.format(value)}%`;
}

function formatShares(value: number | null): string {
  if (value == null) return '—';
  return value.toLocaleString('en-US', { maximumFractionDigits: 4 });
}

function pnlColor(value: number | null): string {
  if (value == null) return 'text-slate-300';
  if (value > 0) return 'text-signal-green';
  if (value < 0) return 'text-signal-red';
  return 'text-slate-300';
}

function buildRowMetrics(positions: readonly PositionResponse[]): PositionRowMetrics[] {
  const rows: PositionRowMetrics[] = positions.map((p) => {
    const shares = parseDecimalString(p.shares);
    const avgCost = parseDecimalString(p.avg_cost);
    const currentPrice = parseDecimalString(p.current_price);
    const unrealizedPnl = parseDecimalString(p.unrealized_pnl);
    const isClosed = p.closed_at != null;
    const marketValue =
      currentPrice != null && shares != null && !isClosed ? currentPrice * shares : null;
    const costBasis = avgCost != null && shares != null ? avgCost * shares : null;
    const unrealizedPct =
      unrealizedPnl != null && costBasis != null && costBasis !== 0
        ? (unrealizedPnl / costBasis) * 100
        : null;
    return {
      position: p,
      marketValue,
      unrealizedPnl,
      unrealizedPct,
      shares,
      avgCost,
      currentPrice,
      allocationPct: null,
      isClosed,
    };
  });
  const totalMarketValue = rows.reduce(
    (acc, r) => acc + (r.isClosed || r.marketValue == null ? 0 : r.marketValue),
    0,
  );
  if (totalMarketValue <= 0) return rows;
  return rows.map((r) =>
    r.isClosed || r.marketValue == null
      ? r
      : { ...r, allocationPct: (r.marketValue / totalMarketValue) * 100 },
  );
}

function compareWithKey(
  a: PositionRowMetrics,
  b: PositionRowMetrics,
  key: PositionsSortKey,
  dir: PositionsSortDir,
): number {
  const av = a[
    key === 'market_value' ? 'marketValue' : key === 'unrealized_pnl' ? 'unrealizedPnl' : 'shares'
  ];
  const bv = b[
    key === 'market_value' ? 'marketValue' : key === 'unrealized_pnl' ? 'unrealizedPnl' : 'shares'
  ];
  // Closed positions and missing metrics sink to the bottom regardless of direction.
  const aClosed = a.isClosed || av == null;
  const bClosed = b.isClosed || bv == null;
  if (aClosed && !bClosed) return 1;
  if (!aClosed && bClosed) return -1;
  if (aClosed && bClosed) return a.position.symbol.localeCompare(b.position.symbol);
  const left = av ?? 0;
  const right = bv ?? 0;
  if (left === right) return a.position.symbol.localeCompare(b.position.symbol);
  return dir === 'desc' ? right - left : left - right;
}

interface SortableHeaderProps {
  label: string;
  sortKey: PositionsSortKey;
  active: boolean;
  dir: PositionsSortDir;
  onClick: (key: PositionsSortKey) => void;
}

function SortableHeader({ label, sortKey, active, dir, onClick }: SortableHeaderProps): JSX.Element {
  const indicator = active ? (dir === 'desc' ? '▼' : '▲') : '';
  return (
    <button
      type="button"
      onClick={() => onClick(sortKey)}
      aria-sort={active ? (dir === 'desc' ? 'descending' : 'ascending') : 'none'}
      className={`inline-flex items-center gap-1 text-xs uppercase tracking-wide focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400 ${
        active ? 'text-slate-100' : 'text-slate-400 hover:text-slate-200'
      }`}
    >
      <span>{label}</span>
      <span aria-hidden="true" className="text-[10px]">
        {indicator}
      </span>
    </button>
  );
}

interface OverflowMenuProps {
  symbol: string;
  onAdd: () => void;
  onReduce: () => void;
  onClose: () => void;
}

function OverflowMenu({ symbol, onAdd, onReduce, onClose }: OverflowMenuProps): JSX.Element {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const menuId = `position-actions-${symbol}`;

  useEffect(() => {
    if (!open) return undefined;
    const onDocClick = (e: MouseEvent): void => {
      if (!containerRef.current) return;
      if (!containerRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onDocClick);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDocClick);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const stopAndRun = useCallback(
    (fn: () => void) => (e: React.MouseEvent) => {
      e.stopPropagation();
      setOpen(false);
      fn();
    },
    [],
  );

  return (
    <div
      ref={containerRef}
      className="relative inline-block"
      onClick={(e) => e.stopPropagation()}
      onKeyDown={(e) => {
        if (e.key === ' ' || e.key === 'Enter') e.stopPropagation();
      }}
    >
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={menuId}
        aria-label={`${symbol} 操作`}
        onClick={(e) => {
          e.stopPropagation();
          setOpen((o) => !o);
        }}
        className="rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-sm text-slate-200 hover:border-sky-500 hover:text-sky-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
      >
        <span aria-hidden="true">⋯</span>
      </button>
      {open && (
        <div
          id={menuId}
          role="menu"
          className="absolute right-0 z-20 mt-1 min-w-[8rem] overflow-hidden rounded-md border border-slate-700 bg-slate-900 text-sm shadow-lg"
        >
          <button
            type="button"
            role="menuitem"
            onClick={stopAndRun(onAdd)}
            className="block w-full px-3 py-2 text-left text-slate-200 hover:bg-slate-800 focus-visible:outline-none focus-visible:bg-slate-800"
          >
            加碼
          </button>
          <button
            type="button"
            role="menuitem"
            onClick={stopAndRun(onReduce)}
            className="block w-full px-3 py-2 text-left text-slate-200 hover:bg-slate-800 focus-visible:outline-none focus-visible:bg-slate-800"
          >
            減碼
          </button>
          <button
            type="button"
            role="menuitem"
            onClick={stopAndRun(onClose)}
            className="block w-full px-3 py-2 text-left text-signal-red hover:bg-signal-red/10 focus-visible:outline-none focus-visible:bg-signal-red/10"
          >
            關閉
          </button>
        </div>
      )}
    </div>
  );
}

interface PositionDetailPanelProps {
  positionId: number;
}

function PositionDetailPanel({ positionId }: PositionDetailPanelProps): JSX.Element {
  const { data, isLoading, isError, refetch } = usePosition(positionId);
  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-xs text-slate-400">
        <LoadingSpinner label="載入交易紀錄…" />
        <span>載入交易紀錄…</span>
      </div>
    );
  }
  if (isError || !data) {
    return (
      <div className="flex items-center justify-between rounded-md border border-signal-red/40 bg-signal-red/10 px-3 py-2 text-xs text-signal-red">
        <span>載入交易紀錄失敗。</span>
        <button
          type="button"
          onClick={() => void refetch()}
          className="underline hover:text-signal-red"
        >
          重試
        </button>
      </div>
    );
  }
  return <TradeLogTable trades={data.recent_trades} />;
}

interface DesktopRowProps {
  metrics: PositionRowMetrics;
  expanded: boolean;
  onToggle: () => void;
  onAdd: () => void;
  onReduce: () => void;
  onClose: () => void;
}

function DesktopRow({
  metrics,
  expanded,
  onToggle,
  onAdd,
  onReduce,
  onClose,
}: DesktopRowProps): JSX.Element {
  const { position, marketValue, allocationPct, shares, avgCost, currentPrice, unrealizedPnl, unrealizedPct, isClosed } =
    metrics;
  const handleKey = (e: React.KeyboardEvent<HTMLTableRowElement>): void => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      onToggle();
    }
  };
  const rowClass = `cursor-pointer border-t border-slate-800 transition hover:bg-slate-900/50 focus-within:bg-slate-900/50 focus-visible:outline-none ${
    isClosed ? 'opacity-60' : ''
  } ${expanded ? 'bg-slate-900/40' : ''}`;
  return (
    <>
      <tr
        tabIndex={0}
        role="button"
        aria-expanded={expanded}
        aria-controls={`position-detail-${position.id}`}
        onClick={onToggle}
        onKeyDown={handleKey}
        className={rowClass}
      >
        <td className="px-3 py-3 align-top">
          <div className="flex items-center gap-2">
            <Link
              to={ROUTES.TICKER.replace(':symbol', position.symbol)}
              onClick={(e) => e.stopPropagation()}
              className="font-mono text-base font-semibold text-slate-100 hover:text-sky-300 hover:underline"
            >
              {position.symbol}
            </Link>
            {isClosed && (
              <span className="rounded-sm border border-slate-700 bg-slate-900 px-1.5 py-0.5 text-[10px] font-medium text-slate-400">
                已平倉
              </span>
            )}
          </div>
        </td>
        <td className="px-3 py-3 text-right align-top">
          <div className="font-mono text-base font-semibold text-slate-100">
            {formatCurrency(marketValue)}
          </div>
          {allocationPct != null && (
            <div className="mt-0.5 text-xs text-slate-500">{formatPercent(allocationPct)}</div>
          )}
        </td>
        <td className="px-3 py-3 text-right align-top font-mono text-sm text-slate-300">
          <span>{formatShares(shares)}</span>
          <span className="px-1 text-slate-600">×</span>
          <span>${formatCurrency(avgCost)}</span>
        </td>
        <td className="px-3 py-3 text-right align-top font-mono text-sm">
          {currentPrice == null ? (
            <span
              className="text-slate-600"
              title="價格更新中"
              aria-label="價格更新中"
            >
              —
            </span>
          ) : (
            <span className="text-slate-200">${formatCurrency(currentPrice)}</span>
          )}
        </td>
        <td className="px-3 py-3 text-right align-top">
          <div className={`font-mono text-sm font-semibold ${pnlColor(unrealizedPnl)}`}>
            {formatSignedCurrency(unrealizedPnl)}
          </div>
          {unrealizedPct != null && (
            <div className={`mt-0.5 text-xs ${pnlColor(unrealizedPnl)}`}>
              ({formatPercent(unrealizedPct, true)})
            </div>
          )}
        </td>
        <td className="px-3 py-3 text-right align-top">
          {!isClosed && (
            <OverflowMenu
              symbol={position.symbol}
              onAdd={onAdd}
              onReduce={onReduce}
              onClose={onClose}
            />
          )}
        </td>
      </tr>
      {expanded && (
        <tr id={`position-detail-${position.id}`} className="bg-slate-950/60">
          <td colSpan={6} className="px-3 py-3">
            <PositionDetailPanel positionId={position.id} />
          </td>
        </tr>
      )}
    </>
  );
}

interface MobileCardProps {
  metrics: PositionRowMetrics;
  expanded: boolean;
  onToggle: () => void;
  onAdd: () => void;
  onReduce: () => void;
  onClose: () => void;
}

function MobileCard({
  metrics,
  expanded,
  onToggle,
  onAdd,
  onReduce,
  onClose,
}: MobileCardProps): JSX.Element {
  const { position, marketValue, allocationPct, shares, avgCost, currentPrice, unrealizedPnl, unrealizedPct, isClosed } =
    metrics;
  const handleKey = (e: React.KeyboardEvent<HTMLDivElement>): void => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      onToggle();
    }
  };
  return (
    <article
      className={`rounded-md border border-slate-800 bg-slate-950/40 ${isClosed ? 'opacity-60' : ''}`}
    >
      <div
        role="button"
        tabIndex={0}
        aria-expanded={expanded}
        aria-controls={`position-detail-mobile-${position.id}`}
        onClick={onToggle}
        onKeyDown={handleKey}
        className="flex cursor-pointer flex-col gap-3 px-3 py-3 hover:bg-slate-900/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
      >
        <div className="flex items-start justify-between gap-3">
          <div className="flex flex-col gap-1">
            <div className="flex items-center gap-2">
              <Link
                to={ROUTES.TICKER.replace(':symbol', position.symbol)}
                onClick={(e) => e.stopPropagation()}
                className="font-mono text-base font-semibold text-slate-100 hover:text-sky-300 hover:underline"
              >
                {position.symbol}
              </Link>
              {isClosed && (
                <span className="rounded-sm border border-slate-700 bg-slate-900 px-1.5 py-0.5 text-[10px] font-medium text-slate-400">
                  已平倉
                </span>
              )}
            </div>
            <div className="font-mono text-xs text-slate-400">
              {formatShares(shares)}
              <span className="px-1 text-slate-600">×</span>${formatCurrency(avgCost)}
            </div>
          </div>
          <div className="flex flex-col items-end gap-1">
            <div className="font-mono text-base font-semibold text-slate-100">
              {formatCurrency(marketValue)}
            </div>
            {allocationPct != null && (
              <div className="text-xs text-slate-500">{formatPercent(allocationPct)}</div>
            )}
          </div>
        </div>
        <div className="flex items-end justify-between gap-3">
          <div className="flex flex-col gap-0.5 text-xs">
            <span className="text-slate-500">現價</span>
            {currentPrice == null ? (
              <span
                className="font-mono text-slate-600"
                title="價格更新中"
                aria-label="價格更新中"
              >
                —
              </span>
            ) : (
              <span className="font-mono text-slate-200">${formatCurrency(currentPrice)}</span>
            )}
          </div>
          <div className="flex flex-col items-end gap-0.5">
            <span className={`font-mono text-sm font-semibold ${pnlColor(unrealizedPnl)}`}>
              {formatSignedCurrency(unrealizedPnl)}
            </span>
            {unrealizedPct != null && (
              <span className={`text-xs ${pnlColor(unrealizedPnl)}`}>
                ({formatPercent(unrealizedPct, true)})
              </span>
            )}
          </div>
          {!isClosed && (
            <OverflowMenu
              symbol={position.symbol}
              onAdd={onAdd}
              onReduce={onReduce}
              onClose={onClose}
            />
          )}
        </div>
      </div>
      {expanded && (
        <div
          id={`position-detail-mobile-${position.id}`}
          className="border-t border-slate-800 px-3 py-3"
        >
          <PositionDetailPanel positionId={position.id} />
        </div>
      )}
    </article>
  );
}

export function PositionsTable({
  positions,
  expandedId,
  onToggle,
  onAdd,
  onReduce,
  onClose,
}: PositionsTableProps): JSX.Element {
  const [sortKey, setSortKey] = useState<PositionsSortKey>('market_value');
  const [sortDir, setSortDir] = useState<PositionsSortDir>('desc');

  const sortedRows = useMemo(() => {
    const enriched = buildRowMetrics(positions);
    const copy = enriched.slice();
    copy.sort((a, b) => compareWithKey(a, b, sortKey, sortDir));
    return copy;
  }, [positions, sortKey, sortDir]);

  const handleSort = useCallback((key: PositionsSortKey) => {
    setSortKey((curr) => {
      if (curr === key) {
        setSortDir((d) => (d === 'desc' ? 'asc' : 'desc'));
        return curr;
      }
      setSortDir('desc');
      return key;
    });
  }, []);

  return (
    <div data-testid="positions-list">
      <div className="hidden md:block">
        <div className="overflow-hidden rounded-md border border-slate-800">
          <table className="w-full text-sm">
            <thead className="bg-slate-900/80 text-slate-400">
              <tr>
                <th scope="col" className="px-3 py-2 text-left font-medium">
                  代碼
                </th>
                <th scope="col" className="px-3 py-2 text-right font-medium">
                  <SortableHeader
                    label="市值"
                    sortKey="market_value"
                    active={sortKey === 'market_value'}
                    dir={sortDir}
                    onClick={handleSort}
                  />
                </th>
                <th scope="col" className="px-3 py-2 text-right font-medium">
                  <SortableHeader
                    label="股數 × 均成本"
                    sortKey="shares"
                    active={sortKey === 'shares'}
                    dir={sortDir}
                    onClick={handleSort}
                  />
                </th>
                <th scope="col" className="px-3 py-2 text-right font-medium">
                  現價
                </th>
                <th scope="col" className="px-3 py-2 text-right font-medium">
                  <SortableHeader
                    label="未實現損益"
                    sortKey="unrealized_pnl"
                    active={sortKey === 'unrealized_pnl'}
                    dir={sortDir}
                    onClick={handleSort}
                  />
                </th>
                <th scope="col" className="px-3 py-2 text-right font-medium">
                  <span className="sr-only">操作</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {sortedRows.map((row) => (
                <DesktopRow
                  key={row.position.id}
                  metrics={row}
                  expanded={expandedId === row.position.id}
                  onToggle={() => onToggle(row.position.id)}
                  onAdd={() => onAdd(row.position)}
                  onReduce={() => onReduce(row.position)}
                  onClose={() => onClose(row.position)}
                />
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <ul className="flex flex-col gap-2 md:hidden">
        {sortedRows.map((row) => (
          <li key={row.position.id}>
            <MobileCard
              metrics={row}
              expanded={expandedId === row.position.id}
              onToggle={() => onToggle(row.position.id)}
              onAdd={() => onAdd(row.position)}
              onReduce={() => onReduce(row.position)}
              onClose={() => onClose(row.position)}
            />
          </li>
        ))}
      </ul>
    </div>
  );
}
