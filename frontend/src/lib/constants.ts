export const ROUTES = {
  LOGIN: '/login',
  DASHBOARD: '/dashboard',
  TICKER: '/ticker/:symbol',
  POSITIONS: '/positions',
  HISTORY: '/history',
  SETTINGS: '/settings',
} as const;

export const COLORS = {
  SIGNAL_GREEN: '#22c55e',
  SIGNAL_YELLOW: '#eab308',
  SIGNAL_RED: '#ef4444',
} as const;

export const API_BASE_URL: string = import.meta.env.VITE_API_URL ?? '';

export const DISCLAIMER_TEXT =
  '此工具僅為個人決策輔助，不構成投資建議。使用者自行承擔所有交易決策風險。';
