export const ROUTES = {
  LOGIN: '/login',
  // DASHBOARD path stays for URL stability; the page label is "市場總覽" in
  // the sidebar nav (renamed in Commit C).
  DASHBOARD: '/dashboard',
  TICKER: '/ticker/:symbol',
  HISTORY: '/history',
  SETTINGS: '/settings',
} as const;

// Signal colours — emerald / amber / rose @ 600 so they're legible on the
// stone-50 light background. Mirrored by `signal` aliases in tailwind.config.
export const COLORS = {
  SIGNAL_GREEN: '#059669',
  SIGNAL_YELLOW: '#d97706',
  SIGNAL_RED: '#e11d48',
} as const;

export const API_BASE_URL: string = import.meta.env.VITE_API_URL ?? '';

export const DISCLAIMER_TEXT =
  '此工具僅為個人決策輔助，不構成投資建議。使用者自行承擔所有交易決策風險。';
