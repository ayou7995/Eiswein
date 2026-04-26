import type { ReactNode } from 'react';

export interface TooltipProps {
  text: string;
  children: ReactNode;
  side?: 'top' | 'bottom';
  className?: string;
}

const SIDE_POSITION: Record<'top' | 'bottom', string> = {
  top: 'bottom-full mb-1.5',
  bottom: 'top-full mt-1.5',
};

export function Tooltip({
  text,
  children,
  side = 'top',
  className = '',
}: TooltipProps): JSX.Element {
  return (
    <span className={`group relative inline-flex items-center ${className}`}>
      {children}
      <span
        role="tooltip"
        className={`pointer-events-none absolute left-1/2 z-50 max-w-xs -translate-x-1/2 whitespace-normal break-words rounded border border-slate-700 bg-slate-800 px-2 py-1 text-xs text-slate-100 opacity-0 shadow-lg transition-opacity duration-150 group-hover:opacity-100 group-focus-within:opacity-100 ${SIDE_POSITION[side]}`}
      >
        {text}
      </span>
    </span>
  );
}
