import { parseDecimalString } from '../api/tickerSignal';
import type { TradeResponse } from '../api/positions';

export interface TradeLogTableProps {
  trades: readonly TradeResponse[];
}

// Trades are recorded with end-of-day timestamps; the time portion is a
// midnight-ET → UTC artifact that adds noise without information.
function formatDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleDateString('zh-TW', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  });
}

function formatShares(raw: string): string {
  const n = parseDecimalString(raw);
  if (n == null) return '—';
  return n.toLocaleString('en-US', { maximumFractionDigits: 4 });
}

function formatCurrency(raw: string | null): string {
  const n = parseDecimalString(raw);
  if (n == null) return '—';
  return n.toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function sideLabel(side: TradeResponse['side']): string {
  return side === 'buy' ? '買' : '賣';
}

function pnlClassName(raw: string | null): string {
  const n = parseDecimalString(raw);
  if (n == null) return 'text-slate-500';
  if (n > 0) return 'text-signal-green';
  if (n < 0) return 'text-signal-red';
  return 'text-slate-300';
}

export function TradeLogTable({ trades }: TradeLogTableProps): JSX.Element {
  if (trades.length === 0) {
    return (
      <p role="status" className="text-sm text-slate-400">
        尚無交易紀錄。
      </p>
    );
  }

  return (
    <div data-testid="trade-log-table">
      {/* Desktop table. Mobile users get the stacked card variant below. */}
      <div className="hidden overflow-hidden rounded-md border border-slate-800 md:block">
        <table className="w-full text-sm">
          <thead className="bg-slate-900/80 text-xs uppercase text-slate-400">
            <tr>
              <th scope="col" className="px-3 py-2 text-left">
                日期
              </th>
              <th scope="col" className="px-3 py-2 text-left">
                買/賣
              </th>
              <th scope="col" className="px-3 py-2 text-right">
                股數
              </th>
              <th scope="col" className="px-3 py-2 text-right">
                價格
              </th>
              <th scope="col" className="px-3 py-2 text-right">
                已實現損益
              </th>
              <th scope="col" className="px-3 py-2 text-left">
                備註
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800">
            {trades.map((trade) => (
              <tr key={trade.id} className="bg-slate-950/40">
                <td className="px-3 py-2 text-xs text-slate-400">
                  {formatDate(trade.executed_at)}
                </td>
                <td className="px-3 py-2">
                  <span
                    className={`rounded px-2 py-0.5 text-xs font-semibold ${
                      trade.side === 'buy'
                        ? 'bg-signal-green/15 text-signal-green'
                        : 'bg-signal-red/15 text-signal-red'
                    }`}
                    aria-label={`${sideLabel(trade.side)}單`}
                  >
                    {sideLabel(trade.side)}
                  </span>
                </td>
                <td className="px-3 py-2 text-right font-mono text-slate-200">
                  {formatShares(trade.shares)}
                </td>
                <td className="px-3 py-2 text-right font-mono text-slate-200">
                  {formatCurrency(trade.price)}
                </td>
                <td className={`px-3 py-2 text-right font-mono ${pnlClassName(trade.realized_pnl)}`}>
                  {trade.realized_pnl == null ? '—' : formatCurrency(trade.realized_pnl)}
                </td>
                <td className="px-3 py-2 text-xs text-slate-400">
                  {trade.note ?? ''}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <ul className="flex flex-col gap-2 md:hidden">
        {trades.map((trade) => (
          <li
            key={trade.id}
            className="rounded-md border border-slate-800 bg-slate-950/40 p-3 text-sm"
          >
            <div className="flex items-center justify-between">
              <span
                className={`rounded px-2 py-0.5 text-xs font-semibold ${
                  trade.side === 'buy'
                    ? 'bg-signal-green/15 text-signal-green'
                    : 'bg-signal-red/15 text-signal-red'
                }`}
              >
                {sideLabel(trade.side)}
              </span>
              <span className="text-xs text-slate-400">
                {formatDate(trade.executed_at)}
              </span>
            </div>
            <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
              <dt className="text-slate-500">股數</dt>
              <dd className="text-right font-mono text-slate-200">
                {formatShares(trade.shares)}
              </dd>
              <dt className="text-slate-500">價格</dt>
              <dd className="text-right font-mono text-slate-200">
                {formatCurrency(trade.price)}
              </dd>
              <dt className="text-slate-500">已實現損益</dt>
              <dd className={`text-right font-mono ${pnlClassName(trade.realized_pnl)}`}>
                {trade.realized_pnl == null ? '—' : formatCurrency(trade.realized_pnl)}
              </dd>
            </dl>
            {trade.note && (
              <p className="mt-2 text-xs text-slate-400">{trade.note}</p>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
