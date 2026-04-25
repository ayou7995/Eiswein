import { useCallback, useMemo, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { EisweinApiError } from '../api/errors';
import {
  applyTradeImport,
  previewTradeImport,
  SUPPORTED_BROKERS,
  brokerKeySchema,
  type ApplyResponse,
  type BrokerKey,
  type ImportIssue,
  type PreviewAction,
  type PreviewResponse,
  type PreviewRow,
} from '../api/importTrades';
import { parseDecimalString } from '../api/tickerSignal';
import { LoadingSpinner } from './LoadingSpinner';
import { Modal } from './Modal';

type Step = 'select' | 'preview' | 'apply';

interface TradeImportModalProps {
  open: boolean;
  onClose: () => void;
}

const CURRENCY_FORMATTER = new Intl.NumberFormat('en-US', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

function formatDateTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString('zh-TW', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function formatShares(raw: string): string {
  const n = parseDecimalString(raw);
  if (n == null) return '—';
  return n.toLocaleString('en-US', { maximumFractionDigits: 4 });
}

function formatPrice(raw: string): string {
  const n = parseDecimalString(raw);
  if (n == null) return '—';
  return CURRENCY_FORMATTER.format(n);
}

function sideLabel(side: 'buy' | 'sell'): string {
  return side === 'buy' ? '買' : '賣';
}

function extractErrorMessage(err: unknown): string {
  if (err instanceof EisweinApiError) {
    if (err.code === 'rate_limited') {
      return '請求過於頻繁，請稍後再試（每分鐘最多 5 次）。';
    }
    if (err.status === 413) {
      return '檔案過大，請確認是否為完整的券商 CSV。';
    }
    if (err.code === 'validation_error' && err.details['reason'] === 'unknown_broker') {
      return '尚未支援此券商。';
    }
    if (err.code === 'validation_error' && err.details['reason'] === 'unsupported_content_type') {
      return '檔案格式無效，請上傳 CSV。';
    }
    return err.message;
  }
  if (err instanceof Error) return err.message;
  return '發生未知錯誤，請稍後再試。';
}

const ROW_BG_BY_ACTION: Record<PreviewAction, string> = {
  import: 'bg-slate-900/40',
  skip_duplicate: 'bg-slate-800/60 opacity-60',
  warn: 'bg-amber-900/30',
  error: 'bg-rose-900/30',
};

const ACTION_LABEL: Record<PreviewAction, string> = {
  import: '匯入',
  skip_duplicate: '重複跳過',
  warn: '警告',
  error: '錯誤',
};

export function TradeImportModal({ open, onClose }: TradeImportModalProps): JSX.Element | null {
  const [step, setStep] = useState<Step>('select');
  const [broker, setBroker] = useState<BrokerKey>('robinhood');
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<PreviewResponse | null>(null);
  const [applyResult, setApplyResult] = useState<ApplyResponse | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [expandedRows, setExpandedRows] = useState<ReadonlySet<number>>(
    () => new Set<number>(),
  );

  const queryClient = useQueryClient();

  const previewMut = useMutation({
    mutationFn: ({ b, f }: { b: BrokerKey; f: File }) => previewTradeImport(b, f),
  });

  const applyMut = useMutation({
    mutationFn: ({ b, f }: { b: BrokerKey; f: File }) => applyTradeImport(b, f),
  });

  const reset = useCallback(() => {
    setStep('select');
    setBroker('robinhood');
    setFile(null);
    setPreview(null);
    setApplyResult(null);
    setErrorMessage(null);
    setExpandedRows(new Set<number>());
    previewMut.reset();
    applyMut.reset();
  }, [previewMut, applyMut]);

  const handleClose = useCallback(() => {
    // Invalidate both positions + position detail caches so the page
    // refetches after a successful import. Safe on abort too — stale
    // data just refreshes.
    if (applyResult && applyResult.summary.imported > 0) {
      void queryClient.invalidateQueries({ queryKey: ['positions'] });
      void queryClient.invalidateQueries({ queryKey: ['position'] });
    }
    reset();
    onClose();
  }, [applyResult, onClose, queryClient, reset]);

  const handlePreview = useCallback(async () => {
    if (!file) return;
    setErrorMessage(null);
    try {
      const result = await previewMut.mutateAsync({ b: broker, f: file });
      setPreview(result);
      setExpandedRows(new Set<number>());
      setStep('preview');
    } catch (err) {
      setErrorMessage(extractErrorMessage(err));
    }
  }, [broker, file, previewMut]);

  const handleApply = useCallback(async () => {
    if (!file) return;
    setErrorMessage(null);
    setStep('apply');
    try {
      const result = await applyMut.mutateAsync({ b: broker, f: file });
      setApplyResult(result);
    } catch (err) {
      setErrorMessage(extractErrorMessage(err));
    }
  }, [broker, file, applyMut]);

  const toggleRow = useCallback((idx: number) => {
    setExpandedRows((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  }, []);

  const goBackToSelect = useCallback(() => {
    setStep('select');
    setErrorMessage(null);
    setPreview(null);
    setExpandedRows(new Set<number>());
  }, []);

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title="匯入交易記錄"
      labelledById="trade-import-modal"
    >
      <div className="flex flex-col gap-4 text-sm text-slate-200">
        {step === 'select' && (
          <SelectStep
            broker={broker}
            onBrokerChange={setBroker}
            file={file}
            onFileChange={setFile}
            onPreview={handlePreview}
            submitting={previewMut.isPending}
            errorMessage={errorMessage}
          />
        )}
        {step === 'preview' && preview && (
          <PreviewStep
            preview={preview}
            expandedRows={expandedRows}
            onToggleRow={toggleRow}
            onBack={goBackToSelect}
            onConfirm={handleApply}
          />
        )}
        {step === 'apply' && (
          <ApplyStep
            pending={applyMut.isPending}
            result={applyResult}
            errorMessage={errorMessage}
            onClose={handleClose}
          />
        )}
      </div>
    </Modal>
  );
}

interface SelectStepProps {
  broker: BrokerKey;
  onBrokerChange: (b: BrokerKey) => void;
  file: File | null;
  onFileChange: (f: File | null) => void;
  onPreview: () => void;
  submitting: boolean;
  errorMessage: string | null;
}

function SelectStep({
  broker,
  onBrokerChange,
  file,
  onFileChange,
  onPreview,
  submitting,
  errorMessage,
}: SelectStepProps): JSX.Element {
  return (
    <div className="flex flex-col gap-4">
      <p className="text-xs text-slate-400">
        上傳券商月結單格式的 CSV，欄位需含
        <code className="mx-1 rounded bg-slate-800 px-1 py-0.5 text-[11px] text-slate-200">
          Activity Date, Instrument, Trans Code, Quantity, Price
        </code>
        。若券商只提供 PDF，請手動整理為符合此格式的 CSV 後上傳。
      </p>

      <label className="flex flex-col gap-1">
        <span className="text-xs font-medium text-slate-300">券商</span>
        <select
          value={broker}
          onChange={(e) => {
            const parsed = brokerKeySchema.safeParse(e.target.value);
            if (parsed.success) onBrokerChange(parsed.data);
          }}
          className="rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
        >
          {SUPPORTED_BROKERS.map(({ key, label }) => (
            <option key={key} value={key}>
              {label}
            </option>
          ))}
        </select>
      </label>

      <label className="flex flex-col gap-1">
        <span className="text-xs font-medium text-slate-300">CSV 檔案</span>
        <input
          type="file"
          accept=".csv,text/csv,application/vnd.ms-excel,text/plain"
          onChange={(e) => onFileChange(e.target.files?.[0] ?? null)}
          className="block w-full text-xs text-slate-400 file:mr-3 file:rounded-md file:border-0 file:bg-sky-600 file:px-3 file:py-2 file:text-sm file:font-semibold file:text-white hover:file:bg-sky-500"
        />
        {file && (
          <span className="text-xs text-slate-500">
            已選擇：{file.name} ({Math.round(file.size / 1024)} KB)
          </span>
        )}
      </label>

      {errorMessage && (
        <div
          role="alert"
          className="rounded-md border border-signal-red/40 bg-signal-red/10 px-3 py-2 text-xs text-signal-red"
        >
          {errorMessage}
        </div>
      )}

      <div className="flex items-center justify-end gap-2">
        <button
          type="button"
          onClick={onPreview}
          disabled={!file || submitting}
          className="rounded-md bg-sky-600 px-4 py-2 text-sm font-semibold text-white hover:bg-sky-500 disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-300"
        >
          {submitting ? '分析中…' : '預覽'}
        </button>
      </div>
    </div>
  );
}

interface PreviewStepProps {
  preview: PreviewResponse;
  expandedRows: ReadonlySet<number>;
  onToggleRow: (idx: number) => void;
  onBack: () => void;
  onConfirm: () => void;
}

function PreviewStep({
  preview,
  expandedRows,
  onToggleRow,
  onBack,
  onConfirm,
}: PreviewStepProps): JSX.Element {
  const { summary, parsed, file_issues: fileIssues, total_rows: totalRows } = preview;
  const canConfirm = summary.would_import > 0;

  const summaryText = useMemo(
    () =>
      `共 ${totalRows} 筆 · 可匯入 ${summary.would_import} · 重複跳過 ${summary.would_skip_duplicate} · 警告 ${summary.warnings} · 錯誤 ${summary.errors}`,
    [
      totalRows,
      summary.would_import,
      summary.would_skip_duplicate,
      summary.warnings,
      summary.errors,
    ],
  );

  return (
    <div className="flex flex-col gap-3">
      <p className="text-xs text-slate-300" aria-live="polite">
        {summaryText}
      </p>

      {fileIssues.length > 0 && (
        <FileIssuesBanner issues={fileIssues} />
      )}

      <div className="max-h-80 overflow-auto rounded-md border border-slate-800">
        <table className="w-full text-xs">
          <caption className="sr-only">CSV 匯入預覽</caption>
          <thead className="sticky top-0 bg-slate-900/90 text-left text-slate-400">
            <tr>
              <th scope="col" className="px-2 py-1.5">#</th>
              <th scope="col" className="px-2 py-1.5">Symbol</th>
              <th scope="col" className="px-2 py-1.5">買/賣</th>
              <th scope="col" className="px-2 py-1.5 text-right">股數</th>
              <th scope="col" className="px-2 py-1.5 text-right">價格</th>
              <th scope="col" className="px-2 py-1.5">時間</th>
              <th scope="col" className="px-2 py-1.5">備註</th>
              <th scope="col" className="px-2 py-1.5 text-right">
                <span className="sr-only">展開</span>
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800">
            {parsed.map((row, idx) => (
              <PreviewTableRow
                key={`${row.record.external_id}-${idx}`}
                index={idx + 1}
                row={row}
                expanded={expandedRows.has(idx)}
                onToggle={() => onToggleRow(idx)}
              />
            ))}
          </tbody>
        </table>
      </div>

      <div className="flex items-center justify-end gap-2">
        <button
          type="button"
          onClick={onBack}
          className="rounded-md border border-slate-700 px-4 py-2 text-sm text-slate-200 hover:bg-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
        >
          返回
        </button>
        <button
          type="button"
          onClick={onConfirm}
          disabled={!canConfirm}
          className="rounded-md bg-sky-600 px-4 py-2 text-sm font-semibold text-white hover:bg-sky-500 disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-300"
        >
          確認匯入
        </button>
      </div>
    </div>
  );
}

interface PreviewTableRowProps {
  index: number;
  row: PreviewRow;
  expanded: boolean;
  onToggle: () => void;
}

function PreviewTableRow({
  index,
  row,
  expanded,
  onToggle,
}: PreviewTableRowProps): JSX.Element {
  const bg = ROW_BG_BY_ACTION[row.action];
  const hasIssues = row.issues.length > 0;
  return (
    <>
      <tr className={bg}>
        <td className="px-2 py-1.5 text-slate-400">{index}</td>
        <td className="px-2 py-1.5 font-mono text-slate-100">{row.record.symbol}</td>
        <td className="px-2 py-1.5">
          <span
            className={`rounded px-1.5 py-0.5 font-semibold ${
              row.record.side === 'buy'
                ? 'bg-signal-green/15 text-signal-green'
                : 'bg-signal-red/15 text-signal-red'
            }`}
            aria-label={`${sideLabel(row.record.side)}單`}
          >
            {sideLabel(row.record.side)}
          </span>
        </td>
        <td className="px-2 py-1.5 text-right font-mono text-slate-200">
          {formatShares(row.record.shares)}
        </td>
        <td className="px-2 py-1.5 text-right font-mono text-slate-200">
          {formatPrice(row.record.price)}
        </td>
        <td className="px-2 py-1.5 whitespace-nowrap text-slate-300">
          {formatDateTime(row.record.executed_at)}
        </td>
        <td className="px-2 py-1.5 text-slate-400">{row.record.note ?? ''}</td>
        <td className="px-2 py-1.5 text-right">
          {hasIssues ? (
            <button
              type="button"
              onClick={onToggle}
              aria-expanded={expanded}
              aria-label={expanded ? '收合訊息' : `展開 ${row.issues.length} 筆訊息`}
              className="rounded px-1.5 py-0.5 text-slate-400 hover:bg-slate-800 hover:text-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
            >
              <span aria-hidden="true">{expanded ? '▾' : '▸'}</span>
            </button>
          ) : (
            <span className="text-slate-600" aria-hidden="true">·</span>
          )}
        </td>
      </tr>
      {expanded && hasIssues && (
        <tr className={bg}>
          <td colSpan={8} className="px-2 pb-2 pt-0">
            <ul className="flex flex-col gap-1 pl-4">
              {row.issues.map((issue, i) => (
                <li
                  key={`${issue.code}-${i}`}
                  className="flex items-start gap-2 text-xs"
                >
                  <SeverityBadge severity={issue.severity} />
                  <span className="text-slate-300">{issue.message}</span>
                </li>
              ))}
              <li className="text-xs text-slate-500">
                處理動作：{ACTION_LABEL[row.action]}
              </li>
            </ul>
          </td>
        </tr>
      )}
    </>
  );
}

interface SeverityBadgeProps {
  severity: ImportIssue['severity'];
}

function SeverityBadge({ severity }: SeverityBadgeProps): JSX.Element {
  const cls =
    severity === 'error'
      ? 'bg-signal-red/15 text-signal-red'
      : 'bg-amber-600/20 text-amber-300';
  const label = severity === 'error' ? '錯誤' : '警告';
  return (
    <span
      className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase ${cls}`}
      aria-label={label}
    >
      {label}
    </span>
  );
}

interface FileIssuesBannerProps {
  issues: readonly ImportIssue[];
}

function FileIssuesBanner({ issues }: FileIssuesBannerProps): JSX.Element {
  return (
    <div
      role="alert"
      className="flex flex-col gap-1 rounded-md border border-signal-red/40 bg-signal-red/10 px-3 py-2 text-xs text-signal-red"
    >
      <span className="font-semibold">檔案層級問題</span>
      <ul className="flex flex-col gap-0.5">
        {issues.map((issue, i) => (
          <li key={`${issue.code}-${i}`}>
            <SeverityBadge severity={issue.severity} /> <span>{issue.message}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

interface ApplyStepProps {
  pending: boolean;
  result: ApplyResponse | null;
  errorMessage: string | null;
  onClose: () => void;
}

function ApplyStep({
  pending,
  result,
  errorMessage,
  onClose,
}: ApplyStepProps): JSX.Element {
  return (
    <div className="flex flex-col gap-3" aria-live="polite">
      {pending && (
        <div className="flex items-center gap-2 text-sm text-slate-300">
          <LoadingSpinner label="匯入中…" />
          <span>匯入中…</span>
        </div>
      )}

      {!pending && errorMessage && (
        <div
          role="alert"
          className="rounded-md border border-signal-red/40 bg-signal-red/10 px-3 py-2 text-xs text-signal-red"
        >
          {errorMessage}
        </div>
      )}

      {!pending && result && (
        <div className="flex flex-col gap-2">
          <p className="text-sm text-signal-green">
            ✅ 匯入成功 {result.summary.imported} 筆 · 跳過{' '}
            {result.summary.skipped_duplicate} · 警告 {result.summary.warnings} · 錯誤{' '}
            {result.summary.errors}
          </p>
          {result.issues.length > 0 && (
            <ul className="flex max-h-48 flex-col gap-1 overflow-auto rounded-md border border-slate-800 bg-slate-950/40 p-2 text-xs">
              {result.issues.map((issue, i) => (
                <li key={`${issue.code}-${i}`} className="flex items-start gap-2">
                  <SeverityBadge severity={issue.severity} />
                  <span className="text-slate-300">{issue.message}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <div className="flex items-center justify-end">
        <button
          type="button"
          onClick={onClose}
          disabled={pending}
          className="rounded-md bg-sky-600 px-4 py-2 text-sm font-semibold text-white hover:bg-sky-500 disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-300"
        >
          關閉
        </button>
      </div>
    </div>
  );
}
