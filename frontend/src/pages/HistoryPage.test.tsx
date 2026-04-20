import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { AuthProvider } from '../hooks/useAuth';
import { resetAuthClient } from '../api/client';
import { HistoryPage } from './HistoryPage';

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

function renderHistory(): void {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 0, gcTime: 0 } },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/history']}>
        <AuthProvider
          initialStatus="authenticated"
          initialUser={{ username: 'admin', is_admin: true }}
        >
          <Routes>
            <Route path="/history" element={<HistoryPage />} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('HistoryPage', () => {
  beforeEach(() => {
    resetAuthClient();
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders each of the three sections independently with happy-path data', async () => {
    const restore = installFetch((url) => {
      if (url.includes('/history/market-posture')) {
        return {
          status: 200,
          body: {
            data: [
              {
                date: '2026-04-16',
                posture: 'normal',
                regime_green_count: 2,
                regime_red_count: 1,
                regime_yellow_count: 1,
              },
              {
                date: '2026-04-17',
                posture: 'offensive',
                regime_green_count: 3,
                regime_red_count: 0,
                regime_yellow_count: 1,
              },
            ],
            total: 2,
            has_more: false,
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
            ],
            total: 1,
            has_more: false,
          },
        };
      }
      if (url.includes('/history/signal-accuracy')) {
        return {
          status: 200,
          body: {
            symbol: 'AAPL',
            horizon: 5,
            total_signals: 10,
            correct: 7,
            accuracy_pct: 70.0,
            by_action: {
              buy: { total: 6, correct: 5, accuracy_pct: 83.3 },
              reduce: { total: 4, correct: 2, accuracy_pct: 50.0 },
            },
          },
        };
      }
      if (url.includes('/history/decisions')) {
        return {
          status: 200,
          body: {
            data: [
              {
                trade_id: 1,
                trade_date: '2026-04-15T15:30:00Z',
                symbol: 'AAPL',
                side: 'buy',
                shares: '10.000000',
                price: '180.000000',
                eiswein_action: 'buy',
                matched_recommendation: true,
              },
            ],
            total: 1,
            has_more: false,
          },
        };
      }
      throw new Error(`unexpected fetch ${url}`);
    });
    try {
      renderHistory();
      await waitFor(() => {
        expect(screen.getByTestId('posture-timeline')).toBeInTheDocument();
      });
      await waitFor(() => {
        expect(screen.getByTestId('accuracy-headline')).toHaveTextContent('70.0%');
      });
      await waitFor(() => {
        expect(screen.getByText('我的決策 vs Eiswein')).toBeInTheDocument();
      });
      expect(screen.getAllByText('AAPL').length).toBeGreaterThan(0);
    } finally {
      restore();
    }
  });

  it('each section renders independently when one endpoint errors', async () => {
    const restore = installFetch((url) => {
      if (url.includes('/history/market-posture')) {
        return {
          status: 500,
          body: {
            error: { code: 'server_error', message: 'oops' },
          },
        };
      }
      if (url.endsWith('/api/v1/watchlist')) {
        return {
          status: 200,
          body: { data: [], total: 0, has_more: false },
        };
      }
      if (url.includes('/history/decisions')) {
        return {
          status: 200,
          body: { data: [], total: 0, has_more: false },
        };
      }
      throw new Error(`unexpected fetch ${url}`);
    });
    try {
      renderHistory();
      // Timeline section shows its error.
      await waitFor(() => {
        expect(screen.getByText('載入市場態勢歷史失敗。')).toBeInTheDocument();
      });
      // Accuracy section still rendered (but empty watchlist message).
      expect(screen.getByText('請先於「設定」加入觀察清單。')).toBeInTheDocument();
      // Decisions empty state still rendered.
      expect(screen.getByText('尚無交易紀錄可對照。')).toBeInTheDocument();
    } finally {
      restore();
    }
  });
});
