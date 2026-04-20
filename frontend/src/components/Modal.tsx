import { useCallback, useEffect, useRef, type ReactNode } from 'react';
import { createPortal } from 'react-dom';

export interface ModalProps {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  // Tests assert on this to find the dialog quickly; defaults to a
  // stable id so multiple instances don't collide.
  labelledById?: string;
}

// Focusable descendant selectors for the focus trap. Kept small on
// purpose — only elements a keyboard user can reach need to be covered.
const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

function getFocusables(container: HTMLElement): HTMLElement[] {
  const nodes = container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR);
  return Array.from(nodes).filter((el) => !el.hasAttribute('aria-hidden'));
}

export function Modal({
  open,
  onClose,
  title,
  children,
  labelledById,
}: ModalProps): JSX.Element | null {
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const previouslyFocusedRef = useRef<HTMLElement | null>(null);
  const headingId = labelledById ?? 'modal-heading';

  const handleKeyDown = useCallback(
    (event: KeyboardEvent): void => {
      if (!open) return;
      if (event.key === 'Escape') {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key === 'Tab') {
        const container = dialogRef.current;
        if (!container) return;
        const focusables = getFocusables(container);
        if (focusables.length === 0) {
          event.preventDefault();
          return;
        }
        const first = focusables[0];
        const last = focusables[focusables.length - 1];
        const active = document.activeElement as HTMLElement | null;
        if (!first || !last) return;
        if (event.shiftKey && active === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && active === last) {
          event.preventDefault();
          first.focus();
        }
      }
    },
    [open, onClose],
  );

  useEffect(() => {
    if (!open) return undefined;
    previouslyFocusedRef.current = document.activeElement as HTMLElement | null;

    // Defer one tick so React commits the dialog to the DOM first.
    const t = window.setTimeout(() => {
      const container = dialogRef.current;
      if (!container) return;
      const focusables = getFocusables(container);
      const first = focusables[0] ?? container;
      first.focus();
    }, 0);

    document.addEventListener('keydown', handleKeyDown);
    const originalOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    return () => {
      window.clearTimeout(t);
      document.removeEventListener('keydown', handleKeyDown);
      document.body.style.overflow = originalOverflow;
      previouslyFocusedRef.current?.focus?.();
    };
  }, [open, handleKeyDown]);

  if (!open) return null;

  return createPortal(
    <div
      data-testid="modal-backdrop"
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/70 px-4 py-6"
      onMouseDown={(event) => {
        // Only close if the mousedown is on the backdrop itself, not a
        // descendant — so a drag-release outside doesn't accidentally
        // dismiss an active dialog.
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={headingId}
        tabIndex={-1}
        className="max-h-[90vh] w-full max-w-md overflow-auto rounded-lg border border-slate-800 bg-slate-900 shadow-2xl"
      >
        <header className="flex items-center justify-between border-b border-slate-800 px-4 py-3">
          <h2 id={headingId} className="text-base font-semibold text-slate-100">
            {title}
          </h2>
          <button
            type="button"
            aria-label="關閉對話框"
            onClick={onClose}
            className="rounded-md px-2 py-1 text-slate-400 hover:bg-slate-800 hover:text-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
          >
            <span aria-hidden="true">✕</span>
          </button>
        </header>
        <div className="p-4">{children}</div>
      </div>
    </div>,
    document.body,
  );
}
