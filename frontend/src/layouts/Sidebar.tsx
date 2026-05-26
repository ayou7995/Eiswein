import { NavLink, useNavigate } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';
import { useSidebarFilter } from '../hooks/useSidebarFilter';
import { SidebarStatusCard } from './SidebarStatusCard';
import { TagFilterRow } from '../components/sidebar/TagFilterRow';
import { SidebarWatchlist } from '../components/sidebar/SidebarWatchlist';
import { AddItemInline } from '../components/sidebar/AddItemInline';
import { ROUTES } from '../lib/constants';

interface NavItem {
  to: string;
  label: string;
  icon: string;
}

const NAV_ITEMS: readonly NavItem[] = [
  { to: ROUTES.DASHBOARD, label: '市場總覽', icon: '📊' },
  { to: ROUTES.HISTORY, label: '歷史', icon: '📅' },
  { to: ROUTES.SETTINGS, label: '設定', icon: '⚙' },
];

function navClass(isActive: boolean): string {
  const base =
    'flex items-center gap-2 rounded-md px-3 py-1.5 text-sm font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500';
  return isActive
    ? `${base} bg-sky-600 text-white`
    : `${base} text-stone-700 hover:bg-stone-100`;
}

interface SidebarProps {
  // When rendered as the off-canvas drawer (below `lg`), each link click
  // should also close the drawer. The desktop sidebar doesn't pass this.
  onItemClick?: () => void;
}

export function Sidebar({ onItemClick }: SidebarProps = {}): JSX.Element {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const filter = useSidebarFilter();

  const handleLogout = async (): Promise<void> => {
    await logout();
    navigate(ROUTES.LOGIN, { replace: true });
  };

  return (
    <div className="flex h-full w-full flex-col gap-3 overflow-y-auto px-3 py-4">
      <header className="flex items-baseline justify-between px-1">
        <span className="text-lg font-bold tracking-tight text-stone-900">
          Eiswein
        </span>
        {user && (
          <span className="text-xs text-stone-400">{user.username}</span>
        )}
      </header>

      <nav aria-label="主要導覽" className="flex flex-col gap-0.5">
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            onClick={onItemClick}
            className={({ isActive }) => navClass(isActive)}
          >
            <span aria-hidden="true">{item.icon}</span>
            <span>{item.label}</span>
          </NavLink>
        ))}
      </nav>

      <SidebarStatusCard />

      <div className="flex flex-col gap-2">
        <label htmlFor="sidebar-search" className="sr-only">
          搜尋代碼
        </label>
        <input
          id="sidebar-search"
          type="search"
          value={filter.search}
          onChange={(e) => filter.setSearch(e.target.value)}
          placeholder="搜尋代碼"
          className="rounded-md border border-stone-300 bg-white px-2 py-1.5 text-sm text-stone-900 placeholder:text-stone-400 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-500"
        />
        <TagFilterRow filter={filter} />
      </div>

      <div className="flex-1 overflow-y-auto">
        <SidebarWatchlist filter={filter} />
      </div>

      <AddItemInline />

      <button
        type="button"
        onClick={() => void handleLogout()}
        className="rounded-md border border-stone-300 px-3 py-1.5 text-xs text-stone-600 hover:bg-stone-100 hover:text-stone-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500"
      >
        登出
      </button>
    </div>
  );
}
