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

  it('renders posture timeline + posture accuracy + symbol ranking', async () => {
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
      if (url.includes('/history/symbol-accuracy-ranking')) {
        return {
          status: 200,
          body: {
            horizon: 20,
            days: 90,
            data: [
              { symbol: 'QCOM', total_signals: 53, correct: 45, accuracy_pct: 84.9 },
              { symbol: 'TSLA', total_signals: 12, correct: 8, accuracy_pct: 66.7 },
              { symbol: 'META', total_signals: 21, correct: 9, accuracy_pct: 42.9 },
            ],
            baseline: { total: 90, spy_up_count: 54, spy_up_pct: 60.0 },
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
      expect(screen.getByTestId('posture-accuracy-headline')).toHaveTextContent(
        '75.0%',
      );
      // Symbol ranking card renders + lists the mocked symbols.
      await waitFor(() => {
        expect(screen.getByText('QCOM')).toBeInTheDocument();
      });
      expect(screen.getByText('TSLA')).toBeInTheDocument();
      expect(screen.getByText('META')).toBeInTheDocument();
    } finally {
      restore();
    }
  });

  it('renders the posture timeline error state independently', async () => {
    const restore = installFetch((url) => {
      if (url.includes('/history/market-posture')) {
        return {
          status: 500,
          body: { error: { code: 'server_error', message: 'oops' } },
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
      if (url.includes('/history/symbol-accuracy-ranking')) {
        return {
          status: 200,
          body: {
            horizon: 20,
            days: 90,
            data: [],
            baseline: { total: 0, spy_up_count: 0, spy_up_pct: 0 },
          },
        };
      }
      throw new Error(`unexpected fetch ${url}`);
    });
    try {
      renderHistory();
      await waitFor(() => {
        expect(screen.getByText('載入市場態勢歷史失敗。')).toBeInTheDocument();
      });
    } finally {
      restore();
    }
  });
});
