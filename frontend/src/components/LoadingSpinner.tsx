interface LoadingSpinnerProps {
  label?: string;
  className?: string;
}

export function LoadingSpinner({
  label = '載入中…',
  className = '',
}: LoadingSpinnerProps): JSX.Element {
  return (
    <div
      role="status"
      aria-live="polite"
      aria-label={label}
      className={`inline-flex items-center gap-2 ${className}`}
    >
      <span
        aria-hidden="true"
        className="h-4 w-4 animate-spin rounded-full border-2 border-slate-500 border-t-sky-400"
      />
      <span className="sr-only">{label}</span>
    </div>
  );
}
