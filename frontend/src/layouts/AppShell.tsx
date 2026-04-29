import { useState } from 'react';
import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';
import { DISCLAIMER_TEXT, ROUTES } from '../lib/constants';

interface NavItem {
  to: string;
  label: string;
}

const NAV_ITEMS: readonly NavItem[] = [
  { to: ROUTES.DASHBOARD, label: '儀表板' },
  { to: ROUTES.HISTORY, label: '歷史' },
  { to: ROUTES.POSITIONS, label: '持倉' },
  { to: ROUTES.SETTINGS, label: '設定' },
];

function linkClass(isActive: boolean): string {
  const base =
    'block rounded-md px-3 py-2 text-sm font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400';
  return isActive
    ? `${base} bg-sky-600 text-white`
    : `${base} text-slate-300 hover:bg-slate-800 hover:text-white`;
}

export function AppShell(): JSX.Element {
  const [mobileOpen, setMobileOpen] = useState(false);
  const { logout, user } = useAuth();
  const navigate = useNavigate();

  const handleLogout = async (): Promise<void> => {
    await logout();
    navigate(ROUTES.LOGIN, { replace: true });
  };

  return (
    <div className="flex min-h-screen flex-col bg-slate-950 text-slate-100">
      <header className="border-b border-slate-800 bg-slate-900/60 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-3">
          <div className="flex items-center gap-3">
            <button
              type="button"
              aria-label="開啟主選單"
              aria-expanded={mobileOpen}
              aria-controls="mobile-nav"
              className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-slate-700 text-slate-200 sm:hidden"
              onClick={() => setMobileOpen((v) => !v)}
            >
              <span aria-hidden="true">☰</span>
            </button>
            <span className="text-lg font-semibold">Eiswein</span>
          </div>

          <nav aria-label="主要導覽" className="hidden sm:block">
            <ul className="flex items-center gap-1">
              {NAV_ITEMS.map((item) => (
                <li key={item.to}>
                  <NavLink to={item.to} className={({ isActive }) => linkClass(isActive)}>
                    {item.label}
                  </NavLink>
                </li>
              ))}
            </ul>
          </nav>

          <div className="flex items-center gap-3">
            {user && (
              <span className="hidden text-xs text-slate-400 sm:inline">
                {user.username}
              </span>
            )}
            <button
              type="button"
              onClick={handleLogout}
              className="rounded-md border border-slate-700 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
            >
              登出
            </button>
          </div>
        </div>

        {mobileOpen && (
          <nav id="mobile-nav" aria-label="主要導覽（行動版）" className="border-t border-slate-800 sm:hidden">
            <ul className="flex flex-col gap-1 px-4 py-3">
              {NAV_ITEMS.map((item) => (
                <li key={item.to}>
                  <NavLink
                    to={item.to}
                    onClick={() => setMobileOpen(false)}
                    className={({ isActive }) => linkClass(isActive)}
                  >
                    {item.label}
                  </NavLink>
                </li>
              ))}
            </ul>
          </nav>
        )}
      </header>

      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">
        <Outlet />
      </main>

      <footer className="border-t border-slate-800 px-4 py-3 text-center text-xs text-slate-500">
        {DISCLAIMER_TEXT}
      </footer>
    </div>
  );
}
