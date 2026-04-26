import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
  type ReactNode,
} from 'react';
import { createPortal } from 'react-dom';

// Hover delay before the popover appears. Short enough to feel responsive,
// long enough that incidental cursor traversals don't flicker tooltips.
const HOVER_OPEN_DELAY_MS = 180;
// Width cap on the popover. Wider than the single-line Tooltip — designed
// to accommodate decision tables.
const POPOVER_MAX_WIDTH_PX = 360;
// Gap between the trigger and the popover.
const POPOVER_GAP_PX = 8;

export interface ExplainableProps {
  title: string;
  children: ReactNode;
  explanation: ReactNode;
  // Visually marks the trigger so users discover hover-ability. Default
  // matches the stop-loss-pill style elsewhere in the app.
  marker?: 'underline' | 'none';
  className?: string;
}

interface PopoverPosition {
  top: number;
  left: number;
  // Whether the popover is rendered above the trigger (true) or below.
  // Caller uses this to flip the small caret/visual hint.
  above: boolean;
}

export function Explainable({
  title,
  children,
  explanation,
  marker = 'underline',
  className = '',
}: ExplainableProps): JSX.Element {
  const triggerRef = useRef<HTMLButtonElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);
  const hoverTimerRef = useRef<number | null>(null);

  const [hovered, setHovered] = useState(false);
  const [pinned, setPinned] = useState(false);
  const [position, setPosition] = useState<PopoverPosition | null>(null);
  const popoverId = useId();

  const open = hovered || pinned;

  const computePosition = useCallback((): void => {
    const trigger = triggerRef.current;
    if (trigger === null) return;
    const rect = trigger.getBoundingClientRect();
    // Flip above when the trigger is in the lower half of the viewport so
    // the popover doesn't get clipped at the bottom edge.
    const viewportH = window.innerHeight;
    const above = rect.top > viewportH * 0.55;
    const top = above
      ? rect.top - POPOVER_GAP_PX
      : rect.bottom + POPOVER_GAP_PX;
    // Center horizontally on the trigger, with viewport-edge clamping.
    const triggerCenter = rect.left + rect.width / 2;
    const halfWidth = POPOVER_MAX_WIDTH_PX / 2;
    const margin = 8;
    const left = Math.max(
      margin,
      Math.min(window.innerWidth - margin - POPOVER_MAX_WIDTH_PX, triggerCenter - halfWidth),
    );
    setPosition({ top, left, above });
  }, []);

  useLayoutEffect(() => {
    if (!open) return;
    computePosition();
    // Recompute on scroll/resize so the popover follows the trigger.
    const handle = (): void => computePosition();
    window.addEventListener('scroll', handle, true);
    window.addEventListener('resize', handle);
    return () => {
      window.removeEventListener('scroll', handle, true);
      window.removeEventListener('resize', handle);
    };
  }, [open, computePosition]);

  useEffect(() => {
    if (!pinned) return;
    const handleClick = (event: MouseEvent): void => {
      const target = event.target as Node;
      if (
        triggerRef.current?.contains(target) ||
        popoverRef.current?.contains(target)
      ) {
        return;
      }
      setPinned(false);
    };
    const handleKey = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') setPinned(false);
    };
    document.addEventListener('mousedown', handleClick);
    document.addEventListener('keydown', handleKey);
    return () => {
      document.removeEventListener('mousedown', handleClick);
      document.removeEventListener('keydown', handleKey);
    };
  }, [pinned]);

  useEffect(() => {
    return () => {
      if (hoverTimerRef.current !== null) {
        window.clearTimeout(hoverTimerRef.current);
      }
    };
  }, []);

  const onMouseEnter = (): void => {
    if (hoverTimerRef.current !== null) return;
    hoverTimerRef.current = window.setTimeout(() => {
      setHovered(true);
      hoverTimerRef.current = null;
    }, HOVER_OPEN_DELAY_MS);
  };

  const onMouseLeave = (): void => {
    if (hoverTimerRef.current !== null) {
      window.clearTimeout(hoverTimerRef.current);
      hoverTimerRef.current = null;
    }
    setHovered(false);
  };

  const onClick = (event: ReactMouseEvent<HTMLButtonElement>): void => {
    // Don't bubble to ancestor click handlers (e.g. <summary> would toggle
    // its <details>). The Explainable should be self-contained.
    event.stopPropagation();
    setPinned((prev) => !prev);
  };

  const markerClass =
    marker === 'underline'
      ? 'cursor-help underline decoration-dotted decoration-slate-600 underline-offset-[3px] hover:decoration-slate-400'
      : 'cursor-help';

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        aria-describedby={open && position !== null ? popoverId : undefined}
        aria-expanded={pinned}
        onMouseEnter={onMouseEnter}
        onMouseLeave={onMouseLeave}
        onFocus={() => setHovered(true)}
        onBlur={() => setHovered(false)}
        onClick={onClick}
        className={`inline rounded-sm bg-transparent p-0 text-left text-inherit focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-sky-400 ${markerClass} ${className}`}
      >
        {children}
      </button>
      {open && position !== null
        ? createPortal(
            <div
              ref={popoverRef}
              id={popoverId}
              role="tooltip"
              style={{
                position: 'fixed',
                top: position.above ? position.top : position.top,
                left: position.left,
                width: POPOVER_MAX_WIDTH_PX,
                transform: position.above ? 'translateY(-100%)' : undefined,
              }}
              className="z-50 rounded-md border border-slate-700 bg-slate-900/98 p-3 text-xs text-slate-200 shadow-xl backdrop-blur"
            >
              <div className="mb-2 flex items-start justify-between gap-2">
                <h4 className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
                  {title}
                </h4>
                {pinned && (
                  <button
                    type="button"
                    aria-label="關閉說明"
                    onClick={() => setPinned(false)}
                    className="text-slate-500 hover:text-slate-200"
                  >
                    ✕
                  </button>
                )}
              </div>
              {explanation}
              {!pinned && (
                <p className="mt-2 text-[10px] text-slate-500">
                  點一下可釘選；Esc 或點外面關閉
                </p>
              )}
            </div>,
            document.body,
          )
        : null}
    </>
  );
}

export interface RuleTableRow {
  condition: string;
  result: string;
  current?: boolean;
}

export interface RuleTableProps {
  rows: ReadonlyArray<RuleTableRow>;
  // Optional preface above the table: one-liner explaining what's
  // being decided. Keep it short — the table is the meat.
  preface?: string;
  // Optional footnote below the table (e.g. "正值 = 上方").
  note?: string;
  // Optional "current value" line, shown below the table to anchor
  // the rule to the user's actual data point.
  currentValueText?: string;
}

export function RuleTable({
  rows,
  preface,
  note,
  currentValueText,
}: RuleTableProps): JSX.Element {
  return (
    <div className="flex flex-col gap-2">
      {preface !== undefined && <p className="text-slate-300">{preface}</p>}
      <table className="w-full text-[11px]">
        <thead className="text-slate-500">
          <tr>
            <th scope="col" className="py-1 pr-2 text-left font-medium">
              條件
            </th>
            <th scope="col" className="py-1 text-left font-medium">
              判定
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800">
          {rows.map((row, idx) => (
            <tr
              key={`${row.condition}-${idx}`}
              className={
                row.current === true
                  ? 'bg-sky-500/10 font-medium text-slate-100'
                  : 'text-slate-300'
              }
            >
              <td className="py-1 pr-2 font-mono">
                {row.current === true && (
                  <span aria-hidden="true" className="mr-1 text-sky-300">
                    ▸
                  </span>
                )}
                {row.condition}
              </td>
              <td className="py-1">{row.result}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {currentValueText !== undefined && (
        <p className="text-[11px] text-sky-300">{currentValueText}</p>
      )}
      {note !== undefined && (
        <p className="text-[10px] text-slate-500">{note}</p>
      )}
    </div>
  );
}
