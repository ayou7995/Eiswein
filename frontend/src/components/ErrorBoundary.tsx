import {
  ErrorBoundary as ReactErrorBoundary,
  type FallbackProps,
} from 'react-error-boundary';
import type { ReactNode } from 'react';

function DefaultFallback({ error, resetErrorBoundary }: FallbackProps): JSX.Element {
  const errorId = Date.now().toString(36);
  // Log only a sanitized message — never the full Error object. The raw
  // stack/component trace is visible in DevTools to anyone with physical
  // access to an unlocked device and can leak prop values or component
  // names. Internal debugging should reproduce the error via tests, not
  // rely on production console traces.
  const safeMessage = error instanceof Error ? error.message : String(error);
  // eslint-disable-next-line no-console
  console.error(`[ErrorBoundary ${errorId}]`, safeMessage);

  return (
    <div
      role="alert"
      aria-live="assertive"
      className="mx-auto flex max-w-lg flex-col gap-4 rounded-lg border border-red-500/40 bg-slate-800/60 p-6 text-slate-100"
    >
      <h2 className="text-xl font-semibold text-red-400">發生錯誤</h2>
      <p className="text-sm text-slate-300">
        頁面暫時無法載入，請重新整理。若問題持續，請檢查系統日誌。
      </p>
      <p className="text-xs text-slate-500">錯誤編號：{errorId}</p>
      <button
        type="button"
        onClick={resetErrorBoundary}
        className="self-start rounded-md bg-sky-600 px-4 py-2 text-sm font-medium text-white hover:bg-sky-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-300"
      >
        重新整理
      </button>
    </div>
  );
}

interface ErrorBoundaryProps {
  children: ReactNode;
}

export function ErrorBoundary({ children }: ErrorBoundaryProps): JSX.Element {
  return (
    <ReactErrorBoundary FallbackComponent={DefaultFallback}>{children}</ReactErrorBoundary>
  );
}
