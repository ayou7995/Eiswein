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

  it('renders the merged posture section and signal section with happy-path data', async () => {
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
      if (url.includes('/history/posture-accuracy')) {
        return {
          status: 200,
          body: {
            horizon: 20,
            days: 90,
            total_signals: 4,
            correct: 3,
            accuracy_pct: 75.0,
            by_posture: {
              offensive: { total: 3, correct: 2, accuracy_pct: 66.7 },
              defensive: { total: 1, correct: 1, accuracy_pct: 100.0 },
            },
            baseline: {
              total: 4,
              spy_up_count: 2,
              spy_up_pct: 50.0,
            },
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
                is_system: false,
                active_onboarding_job_id: null,
              },
            ],
            total: 1,
            has_more: false,
          },
        };
      }
      if (url.includes('/history/ticker-signals')) {
        return {
          status: 200,
          body: {
            symbol: 'AAPL',
            data: [
              { date: '2026-04-01', action: 'hold', close: 175 },
              { date: '2026-04-02', action: 'buy', close: 178 },
              { date: '2026-04-03', action: 'reduce', close: 172 },
            ],
          },
        };
      }
      if (url.includes('/history/signal-accuracy')) {
        return {
          status: 200,
          body: {
            symbol: 'AAPL',
            horizon: 20,
            total_signals: 10,
            correct: 7,
            accuracy_pct: 70.0,
            by_action: {
              buy: { total: 6, correct: 5, accuracy_pct: 83.3 },
              reduce: { total: 4, correct: 2, accuracy_pct: 50.0 },
            },
            baseline: {
              total: 10,
              spy_up_count: 6,
              spy_up_pct: 60.0,
            },
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
      // Both posture-accuracy and signal-accuracy headlines surface a
      // "同期 SPY 上漲 baseline" label — the merged section means the
      // string now appears twice on the page.
      expect(screen.getAllByText('同期 SPY 上漲 baseline').length).toBeGreaterThanOrEqual(2);
      // Posture-accuracy headline shows its own % derived from the
      // mocked posture-accuracy response.
      expect(screen.getByTestId('posture-accuracy-headline')).toHaveTextContent('75.0%');
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
      if (url.includes('/history/posture-accuracy')) {
        return {
          status: 200,
          body: {
            horizon: 20,
            days: 90,
            total_signals: 0,
            correct: 0,
            accuracy_pct: 0,
            by_posture: {},
            baseline: { total: 0, spy_up_count: 0, spy_up_pct: 0 },
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
      renderHistory();
      // Timeline section shows its error.
      await waitFor(() => {
        expect(screen.getByText('載入市場態勢歷史失敗。')).toBeInTheDocument();
      });
      // Accuracy section still rendered (but empty watchlist message).
      expect(screen.getByText('請先於「設定」加入觀察清單。')).toBeInTheDocument();
    } finally {
      restore();
    }
  });
});
