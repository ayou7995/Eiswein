import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { screen, waitFor, render } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { AuthProvider } from '../hooks/useAuth';
import { resetAuthClient } from '../api/client';
import { DashboardPage } from './DashboardPage';

type Handler = (url: string) => { status: number; body: unknown };

function installFetch(handler: Handler): () => void {
  const original = globalThis.fetch;
  const mock = vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === 'string' ? input : input.toString();
    const { status, body } = handler(url);
    return new Response(JSON.stringify(body), {
      status,
      headers: { 'content-type': 'application/json' },
    });
  });
  globalThis.fetch = mock as unknown as typeof fetch;
  return () => {
    globalThis.fetch = original;
  };
}

function renderDashboard(): void {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 0, gcTime: 0 } },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/dashboard']}>
        <AuthProvider
          initialStatus="authenticated"
          initialUser={{ username: 'admin', is_admin: true }}
        >
          <Routes>
            <Route path="/dashboard" element={<DashboardPage />} />
            <Route path="/ticker/:symbol" element={<div>ticker-page</div>} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('DashboardPage', () => {
  beforeEach(() => {
    resetAuthClient();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders market posture, watchlist, and attention alerts on happy path', async () => {
    const restore = installFetch((url) => {
      if (url.endsWith('/api/v1/market-posture')) {
        return {
          status: 200,
          body: {
            date: '2026-04-17',
            timezone: 'America/New_York',
            posture: 'normal',
            posture_label: '正常',
            regime_green_count: 2,
            regime_red_count: 1,
            regime_yellow_count: 1,
            streak_days: 4,
            streak_badge: null,
            pros_cons: [
              {
                category: 'direction',
                tone: 'pro',
                short_label: 'SPX 50/200 多頭排列',
                detail: { ma50: 5000, ma200: 4800 },
                indicator_name: 'spx_ma',
              },
            ],
            indicator_version: '1.0.0',
            computed_at: '2026-04-17T21:30:00Z',
          },
        };
      }
      if (url.endsWith('/api/v1/watchlist')) {
        return {
          status: 200,
          body: {
            data: [
              {
                symbol: 'AAPL',
                data_status: 'ready',
                added_at: '2026-04-10T00:00:00Z',
                last_refresh_at: '2026-04-17T21:00:00Z',
              },
              {
                symbol: 'TSLA',
                data_status: 'ready',
                added_at: '2026-04-10T00:00:00Z',
                last_refresh_at: '2026-04-17T21:00:00Z',
              },
            ],
            total: 2,
            has_more: false,
          },
        };
      }
      if (url.includes('/ticker/AAPL/signal')) {
        return {
          status: 200,
          body: {
            symbol: 'AAPL',
            date: '2026-04-17',
            timezone: 'America/New_York',
            action: 'strong_buy',
            action_label: '強力買入 🟢🟢',
            direction_green_count: 4,
            direction_red_count: 0,
            timing_modifier: 'favorable',
            timing_badge: '✓ 時機好',
            show_timing_modifier: true,
            entry_tiers: {
              aggressive: '180.00',
              ideal: '175.00',
              conservative: '170.00',
              split_suggestion: [30, 40, 30],
            },
            stop_loss: '160.00',
            market_posture_at_compute: 'normal',
            pros_cons: [],
            indicator_version: '1.0.0',
            computed_at: '2026-04-17T21:30:00Z',
          },
        };
      }
      if (url.includes('/ticker/TSLA/signal')) {
        return {
          status: 404,
          body: {
            error: {
              code: 'not_found',
              message: 'Signal unavailable',
              details: { reason: 'signal_unavailable' },
            },
          },
        };
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    try {
      renderDashboard();
      await waitFor(() => {
        expect(screen.getByTestId('market-posture-label')).toHaveTextContent('市場態勢：正常');
      });
      await waitFor(() => {
        expect(screen.getByTestId('watchlist-table')).toBeInTheDocument();
      });
      // AAPL signal is strong_buy → attention list.
      await waitFor(() => {
        expect(screen.getByTestId('attention-list')).toBeInTheDocument();
      });
      expect(screen.getByTestId('attention-list')).toHaveTextContent('AAPL');
      // TSLA 404 → "分析運算中" row.
      expect(screen.getByText('分析運算中')).toBeInTheDocument();
    } finally {
      restore();
    }
  });

  it('renders empty-state when watchlist is empty', async () => {
    const restore = installFetch((url) => {
      if (url.endsWith('/api/v1/market-posture')) {
        return {
          status: 404,
          body: {
            error: {
              code: 'not_found',
              message: 'No snapshot',
              details: { reason: 'no_market_snapshot' },
            },
          },
        };
      }
      if (url.endsWith('/api/v1/watchlist')) {
        return {
          status: 200,
          body: { data: [], total: 0, has_more: false },
        };
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    try {
      renderDashboard();
      await waitFor(() => {
        expect(screen.getByText('等待首次運算（每日收盤後產出）。')).toBeInTheDocument();
      });
      expect(
        screen.getByText('尚未加入任何標的。請前往「設定」新增。'),
      ).toBeInTheDocument();
    } finally {
      restore();
    }
  });
});
