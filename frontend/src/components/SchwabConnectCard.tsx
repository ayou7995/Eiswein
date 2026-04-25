import { useEffect, useMemo, useState } from 'react';
import { EisweinApiError } from '../api/errors';
import { startSchwabOAuth, type SchwabStatus, type SchwabTestResult } from '../api/broker';
import {
  useSchwabConnection,
  useSchwabDisconnect,
  useSchwabTest,
} from '../hooks/useSchwabConnection';
import { relativeTime } from '../lib/time';
import { LoadingSpinner } from './LoadingSpinner';
import { Modal } from './Modal';

// Known OAuth-callback failure codes surface as `?reason=<code>`. Unknown
// codes fall through to a generic "未知錯誤" line so the UI never renders a
// raw English identifier to the user.
const REASON_TRANSLATIONS: Record<string, string> = {
  invalid_grant: '授權碼已失效，請重新連接',
  bad_state: '安全驗證失敗（state 不符），請重試',
  state_mismatch: '安全驗證失敗，請重試',
  missing_code_or_state: '授權流程資料不完整，請重試',
  schwab_not_configured: '系統尚未設定 Schwab API key',
  token_exchange_failed: 'Schwab 授權碼交換失敗',
  reauth_required: 'Schwab 連線已失效，請重新連接',
};

function translateReason(code: string): string {
  return REASON_TRANSLATIONS[code] ?? `未知錯誤：${code}`;
}

type CallbackBanner =
  | { kind: 'success' }
  | { kind: 'error'; reason: string }
  | null;

function readCallbackBanner(): CallbackBanner {
  if (typeof window === 'undefined') return null;
  const params = new URLSearchParams(window.location.search);
  const schwab = params.get('schwab');
  if (schwab === 'connected') return { kind: 'success' };
  if (schwab === 'error') {
    return { kind: 'error', reason: params.get('reason') ?? 'unknown' };
  }
  return null;
}

function clearCallbackParams(): void {
  if (typeof window === 'undefined') return;
  window.history.replaceState({}, '', '/settings');
}

export function SchwabConnectCard(): JSX.Element {
  const statusQuery = useSchwabConnection();
  return (
    <section
      aria-labelledby="schwab-connect-heading"
      className="flex flex-col gap-3 rounded-lg border border-slate-800 bg-slate-900/60 p-4"
    >
      <CallbackBanner />
      {statusQuery.isLoading && (
        <div className="flex items-center gap-2 text-slate-400">
          <LoadingSpinner label="載入 Schwab 連線狀態…" />
          <span className="text-sm">載入中…</span>
        </div>
      )}
      {statusQuery.isError && (
        <div className="flex items-center justify-between rounded-md border border-signal-red/40 bg-signal-red/10 px-3 py-2 text-sm text-signal-red">
          <span>無法載入 Schwab 連線狀態。</span>
          <button
            type="button"
            onClick={() => void statusQuery.refetch()}
            className="underline hover:text-signal-red"
          >
            重試
          </button>
        </div>
      )}
      {statusQuery.data &&
        (statusQuery.data.connected ? (
          <ConnectedView status={statusQuery.data} />
        ) : (
          <DisconnectedView />
        ))}
    </section>
  );
}

function CallbackBanner(): JSX.Element | null {
  // `readCallbackBanner` is cheap but we still want to run it exactly once
  // per mount — useMemo([]) captures the value at first render, then the
  // effect cleans the URL so a refresh doesn't re-trigger.
  const initial = useMemo(() => readCallbackBanner(), []);
  const [banner, setBanner] = useState<CallbackBanner>(initial);

  useEffect(() => {
    if (initial) clearCallbackParams();
  }, [initial]);

  if (!banner) return null;
  const dismiss = (): void => setBanner(null);

  if (banner.kind === 'success') {
    return (
      <div
        role="status"
        aria-live="polite"
        className="flex items-start justify-between rounded-md border border-signal-green/40 bg-signal-green/10 px-3 py-2 text-sm text-signal-green"
      >
        <span>✅ 已成功連接 Schwab</span>
        <DismissButton onDismiss={dismiss} tone="green" />
      </div>
    );
  }
  return (
    <div
      role="alert"
      aria-live="polite"
      className="flex items-start justify-between rounded-md border border-signal-red/40 bg-signal-red/10 px-3 py-2 text-sm text-signal-red"
    >
      <span>❌ Schwab 連接失敗（{translateReason(banner.reason)}）</span>
      <DismissButton onDismiss={dismiss} tone="red" />
    </div>
  );
}

function DismissButton({
  onDismiss,
  tone,
}: {
  onDismiss: () => void;
  tone: 'green' | 'red';
}): JSX.Element {
  const hover = tone === 'green' ? 'hover:text-signal-green' : 'hover:text-signal-red';
  return (
    <button
      type="button"
      aria-label="關閉通知"
      onClick={onDismiss}
      className={`ml-3 rounded-md px-1 text-xs text-slate-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400 ${hover}`}
    >
      <span aria-hidden="true">✕</span>
    </button>
  );
}

function DisconnectedView(): JSX.Element {
  return (
    <>
      <header>
        <h2 id="schwab-connect-heading" className="text-lg font-semibold">
          連接 Schwab 帳戶（選用）
        </h2>
      </header>
      <p className="text-sm leading-relaxed text-slate-400">
        雖然你的資金目前放在別的券商，我們還是可以先驗證 Schwab API
        是否可用，未來移轉帳戶時就能立刻啟用自動對帳與即時成交推送。
      </p>
      <div>
        <button
          type="button"
          onClick={() => startSchwabOAuth()}
          className="inline-flex items-center gap-2 rounded-md bg-sky-600 px-4 py-2 text-sm font-semibold text-white hover:bg-sky-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-300"
        >
          連接 Schwab
        </button>
      </div>
    </>
  );
}

function ConnectedView({ status }: { status: SchwabStatus }): JSX.Element {
  const [testResult, setTestResult] = useState<SchwabTestResult | null>(null);
  const [testError, setTestError] = useState<string | null>(null);
  const [disconnectError, setDisconnectError] = useState<string | null>(null);
  const [showConfirm, setShowConfirm] = useState(false);

  const testMutation = useSchwabTest();
  const disconnectMutation = useSchwabDisconnect();

  const onTest = async (): Promise<void> => {
    setTestError(null);
    setTestResult(null);
    try {
      const result = await testMutation.mutateAsync();
      setTestResult(result);
    } catch (err) {
      if (err instanceof EisweinApiError) {
        if (err.code === 'rate_limited') {
          setTestError('每分鐘最多 10 次');
          return;
        }
        setTestError(err.message);
        return;
      }
      setTestError('測試失敗，請稍後再試。');
    }
  };

  const onConfirmDisconnect = async (): Promise<void> => {
    setDisconnectError(null);
    try {
      await disconnectMutation.mutateAsync();
      setShowConfirm(false);
    } catch (err) {
      if (err instanceof EisweinApiError) {
        if (err.code === 'rate_limited') {
          setDisconnectError('每分鐘最多 10 次');
          return;
        }
        setDisconnectError(err.message);
        return;
      }
      setDisconnectError('中斷失敗，請稍後再試。');
    }
  };

  const accounts = status.accounts ?? [];
  const accountsLine =
    accounts.length === 0
      ? '無'
      : accounts.map((a) => a.nickname ?? a.display_id).join(' · ');
  const permission = status.mkt_data_permission ?? '未知';
  const isNonProfessional = status.mkt_data_permission === 'NP';

  return (
    <>
      <header className="flex items-center gap-2">
        <span
          aria-hidden="true"
          className="h-2.5 w-2.5 rounded-full bg-signal-green"
        />
        <h2 id="schwab-connect-heading" className="text-lg font-semibold">
          Schwab — 已連接
        </h2>
      </header>

      <dl className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        <InfoRow label="帳戶" value={accountsLine} />
        {isNonProfessional ? (
          <InfoRow label="資料權限" value={permission} hint="延遲 15 分鐘 — 非即時" />
        ) : (
          <InfoRow label="資料權限" value={permission} />
        )}
        <InfoRow
          label="上次刷新 refresh token"
          value={relativeTime(status.last_refreshed_at ?? null)}
        />
        <InfoRow label="上次測試" value={formatLastTest(status)} />
      </dl>

      <div
        role="status"
        aria-live="polite"
        className="flex flex-wrap items-center gap-2"
      >
        <button
          type="button"
          onClick={() => void onTest()}
          disabled={testMutation.isPending}
          className="inline-flex items-center gap-2 rounded-md bg-sky-600 px-4 py-2 text-sm font-semibold text-white hover:bg-sky-500 disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-300"
        >
          {testMutation.isPending && <LoadingSpinner label="測試中…" />}
          <span>{testMutation.isPending ? '測試中…' : '測試連線'}</span>
        </button>
        <button
          type="button"
          onClick={() => setShowConfirm(true)}
          className="inline-flex items-center gap-2 rounded-md bg-rose-700 px-4 py-2 text-sm font-semibold text-white hover:bg-rose-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rose-300"
        >
          中斷連接
        </button>
        {testResult && testResult.success && (
          <span className="text-sm text-signal-green">
            ✅ 連線正常 · {testResult.account_count ?? 0} 個帳戶 ·{' '}
            {testResult.mkt_data_permission ?? '未知'} · 延遲{' '}
            {testResult.latency_ms ?? 0}ms
          </span>
        )}
        {testResult && !testResult.success && (
          <span className="text-sm text-signal-red">
            ❌ {testResult.error?.message ?? '連線失敗'}
          </span>
        )}
        {testError && <span className="text-sm text-signal-red">❌ {testError}</span>}
      </div>

      <Modal
        open={showConfirm}
        onClose={() => {
          if (!disconnectMutation.isPending) setShowConfirm(false);
        }}
        title="中斷 Schwab 連接"
        labelledById="schwab-disconnect-heading"
      >
        <div className="flex flex-col gap-4">
          <p className="text-sm leading-relaxed text-slate-300">
            中斷連接會刪除 Schwab refresh token，下次需要重新授權。確定要中斷嗎？
          </p>
          {disconnectError && (
            <p role="alert" className="text-sm text-signal-red">
              {disconnectError}
            </p>
          )}
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setShowConfirm(false)}
              disabled={disconnectMutation.isPending}
              className="rounded-md border border-slate-700 px-4 py-2 text-sm text-slate-200 hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
            >
              取消
            </button>
            <button
              type="button"
              onClick={() => void onConfirmDisconnect()}
              disabled={disconnectMutation.isPending}
              className="inline-flex items-center gap-2 rounded-md bg-rose-700 px-4 py-2 text-sm font-semibold text-white hover:bg-rose-600 disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rose-300"
            >
              {disconnectMutation.isPending && <LoadingSpinner label="中斷中…" />}
              <span>{disconnectMutation.isPending ? '中斷中…' : '確認中斷'}</span>
            </button>
          </div>
        </div>
      </Modal>
    </>
  );
}

function formatLastTest(status: SchwabStatus): string {
  if (!status.last_test_at) return '尚未測試';
  const when = relativeTime(status.last_test_at);
  const outcome = status.last_test_status === 'success' ? '成功' : '失敗';
  const latency =
    typeof status.last_test_latency_ms === 'number'
      ? ` · ${status.last_test_latency_ms}ms`
      : '';
  return `${when} · ${outcome}${latency}`;
}

interface InfoRowProps {
  label: string;
  value: string;
  hint?: string;
}

function InfoRow({ label, value, hint }: InfoRowProps): JSX.Element {
  return (
    <div className="rounded-md border border-slate-800 bg-slate-900/40 p-3">
      <dt className="text-xs text-slate-400">{label}</dt>
      <dd className="mt-0.5 font-mono text-sm text-slate-100">{value}</dd>
      {hint && <p className="mt-1 text-xs text-slate-500">{hint}</p>}
    </div>
  );
}
