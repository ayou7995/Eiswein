import type { ReactNode } from 'react';

export interface TooltipProps {
  text: string;
  children: ReactNode;
  side?: 'top' | 'bottom';
  className?: string;
}

const SIDE_POSITION: Record<'top' | 'bottom', string> = {
  top: 'bottom-full mb-1',
  bottom: 'top-full mt-1',
};

export function Tooltip({
  text,
  children,
  side = 'top',
  className = '',
}: TooltipProps): JSX.Element {
  // `w-max` (= width: max-content) escapes the parent's narrow available
  // width — without it, an absolute tooltip inside a narrow span wraps
  // one CJK character per line. Single-line by design; if a tooltip needs
  // wrapping, the calling code should use shorter text instead.
  return (
    <span className={`group relative inline-flex items-center ${className}`}>
      {children}
      <span
        role="tooltip"
        className={`pointer-events-none absolute left-1/2 z-50 w-max -translate-x-1/2 whitespace-nowrap rounded-sm bg-slate-900/95 px-1.5 py-0.5 text-[11px] leading-tight text-slate-200 opacity-0 shadow-md transition-opacity duration-100 group-hover:opacity-100 group-focus-within:opacity-100 ${SIDE_POSITION[side]}`}
      >
        {text}
      </span>
    </span>
  );
}
