import { useCallback, useEffect, useState } from 'react';
import { Outlet } from 'react-router-dom';
import { Sidebar } from './Sidebar';
import { DISCLAIMER_TEXT } from '../lib/constants';

// AppShell — light-theme two-column composition. Sidebar on the left (340px,
// fixed), main content on the right (max-w-[1100px], centered). Below `lg`
// the sidebar hides and a hamburger button toggles an off-canvas drawer
// with ESC + backdrop close. Focus management lives in the drawer block
// rather than a separate Modal because the sidebar already needs to be
// fully interactive when open — Modal's focus trap would conflict with
// `<NavLink>` keyboard nav.
export function AppShell(): JSX.Element {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const closeDrawer = useCallback(() => setDrawerOpen(false), []);

  useEffect(() => {
    if (!drawerOpen) return undefined;
    const onKeydown = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') {
        event.preventDefault();
        closeDrawer();
      }
    };
    const original = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    document.addEventListener('keydown', onKeydown);
    return () => {
      document.body.style.overflow = original;
      document.removeEventListener('keydown', onKeydown);
    };
  }, [drawerOpen, closeDrawer]);

  return (
    <div className="flex min-h-screen bg-stone-50 text-stone-900">
      <aside
        aria-label="主要導覽側欄"
        className="hidden border-r border-stone-200 bg-white lg:flex lg:h-screen lg:w-[340px] lg:shrink-0 lg:sticky lg:top-0"
      >
        <Sidebar />
      </aside>

      <div className="flex min-h-screen flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-stone-200 bg-white/80 px-4 py-2 backdrop-blur lg:hidden">
          <button
            type="button"
            aria-label="開啟側欄"
            aria-expanded={drawerOpen}
            aria-controls="sidebar-drawer"
            onClick={() => setDrawerOpen(true)}
            className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-stone-300 text-stone-700 hover:bg-stone-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500"
          >
            <span aria-hidden="true">☰</span>
          </button>
          <span className="text-base font-semibold tracking-tight">Eiswein</span>
          <span className="h-9 w-9" aria-hidden="true" />
        </header>

        <main className="w-full flex-1 px-4 py-6 sm:px-6 lg:px-8">
          <Outlet />
        </main>

        <footer className="border-t border-stone-200 px-4 py-3 text-center text-xs text-stone-500">
          {DISCLAIMER_TEXT}
        </footer>
      </div>

      {drawerOpen && (
        <div
          data-testid="sidebar-drawer-backdrop"
          className="fixed inset-0 z-40 bg-black/30 lg:hidden"
          onClick={closeDrawer}
          onKeyDown={(e) => {
            if (e.key === 'Escape') closeDrawer();
          }}
          role="presentation"
        >
          <aside
            id="sidebar-drawer"
            aria-label="主要導覽側欄"
            className="absolute inset-y-0 left-0 flex w-[320px] max-w-[85vw] flex-col bg-white shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <Sidebar onItemClick={closeDrawer} />
          </aside>
        </div>
      )}
    </div>
  );
}
