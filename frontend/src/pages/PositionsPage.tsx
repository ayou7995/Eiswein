import { useCallback, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { LoadingSpinner } from '../components/LoadingSpinner';
import { Modal } from '../components/Modal';
import { PositionForm, type PositionFormValues } from '../components/PositionForm';
import { TradeLogTable } from '../components/TradeLogTable';
import { AllocationPieChart, type PieSlice } from '../components/charts/AllocationPieChart';
import {
  useAddToPosition,
  useClosePosition,
  useCreatePosition,
  usePosition,
  usePositions,
  useReducePosition,
} from '../hooks/usePositions';
import { useWatchlist } from '../hooks/useWatchlist';
import { EisweinApiError } from '../api/errors';
import { parseDecimalString } from '../api/tickerSignal';
import type { PositionResponse } from '../api/positions';
import { ROUTES } from '../lib/constants';

type PositionsTab = 'open' | 'all';

type ModalState =
  | { kind: 'closed' }
  | { kind: 'open' }
  | { kind: 'add'; position: PositionResponse }
  | { kind: 'reduce'; position: PositionResponse }
  | { kind: 'close-confirm'; position: PositionResponse };

const CURRENCY_FORMATTER = new Intl.NumberFormat('en-US', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

function formatCurrency(value: number | null): string {
  if (value == null) return '—';
  return CURRENCY_FORMATTER.format(value);
}

function formatShares(raw: string): string {
  const n = parseDecimalString(raw);
  if (n == null) return '—';
  return n.toLocaleString('en-US', { maximumFractionDigits: 4 });
}

function pnlClass(value: number | null): string {
  if (value == null) return 'text-slate-300';
  if (value > 0) return 'text-signal-green';
  if (value < 0) return 'text-signal-red';
  return 'text-slate-300';
}

function isoForServer(localValue: string): string {
  // react-hook-form gives us "YYYY-MM-DDTHH:mm" (no seconds, no zone).
  // Treat it as local time; Date.toISOString() converts to UTC.
  const date = new Date(localValue);
  if (Number.isNaN(date.getTime())) return new Date().toISOString();
  return date.toISOString();
}

function extractServerError(err: unknown): string {
  if (err instanceof EisweinApiError) {
    if (err.code === 'position_conflict' || err.details['reason'] === 'has_remaining_shares') {
      return '請先將股數歸零後再關閉。';
    }
    if (err.code === 'symbol_not_on_watchlist' || err.details['reason'] === 'symbol_not_on_watchlist') {
      return '該代碼不在觀察清單中，請先加入。';
    }
    if (err.code === 'validation_error') {
      return err.message ?? '輸入資料無效。';
    }
    if (err.code === 'rate_limited') {
      return '請求過於頻繁，請稍後再試。';
    }
    return err.message;
  }
  return '發生未知錯誤，請稍後再試。';
}

export function PositionsPage(): JSX.Element {
  const [tab, setTab] = useState<PositionsTab>('open');
  const [modal, setModal] = useState<ModalState>({ kind: 'closed' });
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  const { data, isLoading, isError, refetch } = usePositions(tab === 'all');
  const watchlist = useWatchlist();

  const createMut = useCreatePosition();
  const addMut = useAddToPosition();
  const reduceMut = useReducePosition();
  const closeMut = useClosePosition();

  const positions = useMemo(() => data?.data ?? [], [data]);

  const closeModal = useCallback(() => {
    setModal({ kind: 'closed' });
    setFormError(null);
  }, []);

  const availableSymbols = useMemo(
    () => (watchlist.data?.data.map((w) => w.symbol) ?? []).slice().sort((a, b) => a.localeCompare(b)),
    [watchlist.data],
  );

  const summary = useMemo(() => {
    let marketValue = 0;
    let unrealized = 0;
    let openCount = 0;
    positions.forEach((p) => {
      if (p.closed_at) return;
      openCount += 1;
      const price = parseDecimalString(p.current_price);
      const shares = parseDecimalString(p.shares);
      if (price != null && shares != null) {
        // Sum of display-only values — acceptable float usage per task spec.
        marketValue += price * shares;
      }
      const u = parseDecimalString(p.unrealized_pnl);
      if (u != null) unrealized += u;
    });
    return { marketValue, unrealized, openCount };
  }, [positions]);

  const allocationSlices = useMemo<PieSlice[]>(
    () =>
      positions
        .filter((p) => p.closed_at == null)
        .map((p) => {
          const price = parseDecimalString(p.current_price);
          const shares = parseDecimalString(p.shares);
          const value = price != null && shares != null ? price * shares : 0;
          return { label: p.symbol, value };
        })
        .filter((s) => s.value > 0),
    [positions],
  );

  const submitOpen = useCallback(
    async (values: PositionFormValues): Promise<void> => {
      setFormError(null);
      try {
        await createMut.mutateAsync({
          symbol: values.symbol,
          shares: values.shares,
          price: values.price,
          executed_at: isoForServer(values.executedAt),
          note: values.note,
        });
        closeModal();
      } catch (err) {
        setFormError(extractServerError(err));
      }
    },
    [createMut, closeModal],
  );

  const submitAdd = useCallback(
    async (id: number, values: PositionFormValues): Promise<void> => {
      setFormError(null);
      try {
        await addMut.mutateAsync({
          id,
          input: {
            shares: values.shares,
            price: values.price,
            executed_at: isoForServer(values.executedAt),
            note: values.note,
          },
        });
        closeModal();
      } catch (err) {
        setFormError(extractServerError(err));
      }
    },
    [addMut, closeModal],
  );

  const submitReduce = useCallback(
    async (id: number, values: PositionFormValues): Promise<void> => {
      setFormError(null);
      try {
        await reduceMut.mutateAsync({
          id,
          input: {
            shares: values.shares,
            price: values.price,
            executed_at: isoForServer(values.executedAt),
            note: values.note,
          },
        });
        closeModal();
      } catch (err) {
        setFormError(extractServerError(err));
      }
    },
    [reduceMut, closeModal],
  );

  const confirmClose = useCallback(
    async (id: number): Promise<void> => {
      setFormError(null);
      try {
        await closeMut.mutateAsync(id);
        closeModal();
      } catch (err) {
        setFormError(extractServerError(err));
      }
    },
    [closeMut, closeModal],
  );

  const handleRowClick = useCallback((id: number) => {
    setExpandedId((curr) => (curr === id ? null : id));
  }, []);

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-col">
          <h1 className="text-2xl font-semibold">持倉管理</h1>
          <p className="text-xs text-slate-500">持倉新增、加碼、減碼與交易紀錄。</p>
        </div>
        <button
          type="button"
          onClick={() => {
            setModal({ kind: 'open' });
          }}
          className="rounded-md bg-sky-600 px-4 py-2 text-sm font-semibold text-white hover:bg-sky-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-300"
        >
          開新持倉
        </button>
      </header>

      <TabSwitcher tab={tab} onChange={setTab} />

      <SummaryRow
        marketValue={summary.marketValue}
        unrealized={summary.unrealized}
        openCount={summary.openCount}
      />

      <section
        aria-labelledby="allocation-heading"
        className="flex flex-col gap-3 rounded-lg border border-slate-800 bg-slate-900/60 p-4"
      >
        <header>
          <h2 id="allocation-heading" className="text-lg font-semibold">
            資產配置
          </h2>
        </header>
        <AllocationPieChart slices={allocationSlices} />
      </section>

      <section
        aria-labelledby="positions-heading"
        className="flex flex-col gap-3 rounded-lg border border-slate-800 bg-slate-900/60 p-4"
      >
        <header className="flex items-baseline justify-between">
          <h2 id="positions-heading" className="text-lg font-semibold">
            持倉明細
          </h2>
          {data && (
            <span className="text-xs text-slate-500">{data.total} 筆</span>
          )}
        </header>

        {isLoading && (
          <div className="flex items-center gap-2 text-slate-400">
            <LoadingSpinner label="載入持倉…" />
            <span className="text-sm">載入持倉…</span>
          </div>
        )}

        {isError && (
          <div className="flex items-center justify-between rounded-md border border-signal-red/40 bg-signal-red/10 px-3 py-2 text-sm text-signal-red">
            <span>載入持倉失敗。</span>
            <button
              type="button"
              onClick={() => void refetch()}
              className="underline hover:text-signal-red"
            >
              重試
            </button>
          </div>
        )}

        {!isLoading && !isError && positions.length === 0 && (
          <p role="status" className="text-sm text-slate-400">
            {tab === 'open' ? '目前沒有開倉中的持倉。' : '尚無任何持倉紀錄。'}
          </p>
        )}

        {positions.length > 0 && (
          <PositionsTable
            positions={positions}
            expandedId={expandedId}
            onToggle={handleRowClick}
            onAdd={(p) => setModal({ kind: 'add', position: p })}
            onReduce={(p) => setModal({ kind: 'reduce', position: p })}
            onClose={(p) => setModal({ kind: 'close-confirm', position: p })}
          />
        )}
      </section>

      {modal.kind === 'open' && (
        <Modal
          open
          onClose={closeModal}
          title="開新持倉"
          labelledById="position-modal-open"
        >
          <PositionForm
            mode="open"
            availableSymbols={availableSymbols}
            onSubmit={submitOpen}
            onCancel={closeModal}
            submitError={formError}
            submitting={createMut.isPending}
          />
        </Modal>
      )}

      {modal.kind === 'add' && (
        <Modal
          open
          onClose={closeModal}
          title={`${modal.position.symbol} 加碼`}
          labelledById="position-modal-add"
        >
          <PositionForm
            mode="add"
            symbol={modal.position.symbol}
            onSubmit={(values) => submitAdd(modal.position.id, values)}
            onCancel={closeModal}
            submitError={formError}
            submitting={addMut.isPending}
          />
        </Modal>
      )}

      {modal.kind === 'reduce' && (
        <Modal
          open
          onClose={closeModal}
          title={`${modal.position.symbol} 減碼`}
          labelledById="position-modal-reduce"
        >
          <PositionForm
            mode="reduce"
            symbol={modal.position.symbol}
            maxShares={modal.position.shares}
            onSubmit={(values) => submitReduce(modal.position.id, values)}
            onCancel={closeModal}
            submitError={formError}
            submitting={reduceMut.isPending}
          />
        </Modal>
      )}

      {modal.kind === 'close-confirm' && (
        <Modal
          open
          onClose={closeModal}
          title={`關閉 ${modal.position.symbol}`}
          labelledById="position-modal-close"
        >
          <div className="flex flex-col gap-4 text-sm text-slate-200">
            <p>
              關閉後該持倉將標記為已平倉。僅能關閉股數為 0 的持倉；若仍有股數，請先減碼至 0。
            </p>
            <p className="text-xs text-slate-400">
              目前股數：
              <span className="font-mono">{formatShares(modal.position.shares)}</span>
            </p>
            {formError && (
              <div
                role="alert"
                className="rounded-md border border-signal-red/40 bg-signal-red/10 px-3 py-2 text-xs text-signal-red"
              >
                {formError}
              </div>
            )}
            <div className="flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={closeModal}
                className="rounded-md border border-slate-700 px-4 py-2 text-sm text-slate-200 hover:bg-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
              >
                取消
              </button>
              <button
                type="button"
                onClick={() => void confirmClose(modal.position.id)}
                disabled={closeMut.isPending}
                className="rounded-md bg-signal-red/80 px-4 py-2 text-sm font-semibold text-white hover:bg-signal-red disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-signal-red"
              >
                {closeMut.isPending ? '關閉中…' : '確認關閉'}
              </button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}

interface TabSwitcherProps {
  tab: PositionsTab;
  onChange: (next: PositionsTab) => void;
}

function TabSwitcher({ tab, onChange }: TabSwitcherProps): JSX.Element {
  const tabs: readonly { value: PositionsTab; label: string }[] = [
    { value: 'open', label: '開倉中' },
    { value: 'all', label: '全部 (含已平倉)' },
  ];
  return (
    <div
      role="tablist"
      aria-label="持倉篩選"
      className="inline-flex rounded-md border border-slate-700 bg-slate-900/40 p-0.5"
    >
      {tabs.map((t) => {
        const active = t.value === tab;
        return (
          <button
            key={t.value}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onChange(t.value)}
            className={`rounded px-3 py-1 text-xs font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400 ${
              active ? 'bg-sky-600 text-white' : 'text-slate-300 hover:bg-slate-800 hover:text-white'
            }`}
          >
            {t.label}
          </button>
        );
      })}
    </div>
  );
}

interface SummaryRowProps {
  marketValue: number;
  unrealized: number;
  openCount: number;
}

function SummaryRow({ marketValue, unrealized, openCount }: SummaryRowProps): JSX.Element {
  return (
    <dl className="grid grid-cols-1 gap-3 sm:grid-cols-3">
      <Stat label="總市值" value={formatCurrency(marketValue)} />
      <Stat
        label="總未實現損益"
        value={formatCurrency(unrealized)}
        valueClass={pnlClass(unrealized)}
      />
      <Stat label="開倉數" value={`${openCount}`} />
    </dl>
  );
}

interface StatProps {
  label: string;
  value: string;
  valueClass?: string;
}

function Stat({ label, value, valueClass = 'text-slate-100' }: StatProps): JSX.Element {
  return (
    <div className="rounded-md border border-slate-800 bg-slate-900/60 px-3 py-2">
      <dt className="text-xs text-slate-400">{label}</dt>
      <dd className={`mt-0.5 font-mono text-lg ${valueClass}`}>{value}</dd>
    </div>
  );
}

interface PositionsTableProps {
  positions: readonly PositionResponse[];
  expandedId: number | null;
  onToggle: (id: number) => void;
  onAdd: (p: PositionResponse) => void;
  onReduce: (p: PositionResponse) => void;
  onClose: (p: PositionResponse) => void;
}

function PositionsTable({
  positions,
  expandedId,
  onToggle,
  onAdd,
  onReduce,
  onClose,
}: PositionsTableProps): JSX.Element {
  return (
    <div className="flex flex-col gap-2" data-testid="positions-list">
      {positions.map((p) => (
        <PositionRow
          key={p.id}
          position={p}
          expanded={expandedId === p.id}
          onToggle={() => onToggle(p.id)}
          onAdd={() => onAdd(p)}
          onReduce={() => onReduce(p)}
          onClose={() => onClose(p)}
        />
      ))}
    </div>
  );
}

interface PositionRowProps {
  position: PositionResponse;
  expanded: boolean;
  onToggle: () => void;
  onAdd: () => void;
  onReduce: () => void;
  onClose: () => void;
}

function PositionRow({
  position,
  expanded,
  onToggle,
  onAdd,
  onReduce,
  onClose,
}: PositionRowProps): JSX.Element {
  const unrealized = parseDecimalString(position.unrealized_pnl);
  const currentPrice = parseDecimalString(position.current_price);
  const isClosed = position.closed_at != null;

  return (
    <article className="rounded-md border border-slate-800 bg-slate-950/40">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
        aria-controls={`position-detail-${position.id}`}
        className="flex w-full flex-wrap items-center justify-between gap-3 px-3 py-3 text-left hover:bg-slate-900/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
      >
        <div className="flex flex-col">
          <Link
            to={ROUTES.TICKER.replace(':symbol', position.symbol)}
            onClick={(e) => e.stopPropagation()}
            className="font-mono text-base font-semibold text-slate-100 hover:underline"
          >
            {position.symbol}
          </Link>
          {isClosed && (
            <span className="text-xs text-slate-500">已平倉</span>
          )}
        </div>
        <dl className="grid flex-1 grid-cols-2 gap-x-4 gap-y-1 text-xs sm:grid-cols-4">
          <dt className="text-slate-500">股數</dt>
          <dd className="font-mono text-slate-200">{formatShares(position.shares)}</dd>
          <dt className="text-slate-500">均成本</dt>
          <dd className="font-mono text-slate-200">
            {formatCurrency(parseDecimalString(position.avg_cost))}
          </dd>
          <dt className="text-slate-500">現價</dt>
          <dd className="font-mono text-slate-200">{formatCurrency(currentPrice)}</dd>
          <dt className="text-slate-500">未實現損益</dt>
          <dd className={`font-mono ${pnlClass(unrealized)}`}>{formatCurrency(unrealized)}</dd>
        </dl>
      </button>

      {!isClosed && (
        <div className="flex flex-wrap items-center gap-2 border-t border-slate-800 bg-slate-900/40 px-3 py-2">
          <ActionButton onClick={onAdd}>加碼</ActionButton>
          <ActionButton onClick={onReduce}>減碼</ActionButton>
          <ActionButton onClick={onClose} destructive>
            關閉
          </ActionButton>
        </div>
      )}

      {expanded && (
        <div id={`position-detail-${position.id}`} className="border-t border-slate-800 p-3">
          <PositionDetailPanel positionId={position.id} />
        </div>
      )}
    </article>
  );
}

interface ActionButtonProps {
  onClick: () => void;
  children: React.ReactNode;
  destructive?: boolean;
}

function ActionButton({ onClick, children, destructive = false }: ActionButtonProps): JSX.Element {
  return (
    <button
      type="button"
      onClick={onClick}
      className={
        destructive
          ? 'rounded-md border border-signal-red/40 bg-slate-900 px-3 py-1 text-xs text-signal-red hover:border-signal-red hover:bg-signal-red/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-signal-red'
          : 'rounded-md border border-slate-700 bg-slate-900 px-3 py-1 text-xs text-slate-200 hover:border-sky-500 hover:text-sky-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400'
      }
    >
      {children}
    </button>
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
