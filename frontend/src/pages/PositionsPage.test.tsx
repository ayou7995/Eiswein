import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { AuthProvider } from '../hooks/useAuth';
import { resetAuthClient } from '../api/client';
import { PositionsPage } from './PositionsPage';

type Handler = (url: string, init?: RequestInit) => { status: number; body: unknown };

function installFetch(handler: Handler): () => void {
  const original = globalThis.fetch;
  const mock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.toString();
    const { status, body } = handler(url, init);
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

function renderPositions(): void {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 0, gcTime: 0 } },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/positions']}>
        <AuthProvider
          initialStatus="authenticated"
          initialUser={{ username: 'admin', is_admin: true }}
        >
          <Routes>
            <Route path="/positions" element={<PositionsPage />} />
            <Route path="/ticker/:symbol" element={<div>ticker-page</div>} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const POSITION = {
  id: 7,
  symbol: 'AAPL',
  shares: '10.000000',
  avg_cost: '180.000000',
  opened_at: '2026-04-10T15:30:00Z',
  closed_at: null,
  notes: null,
  current_price: '190.000000',
  unrealized_pnl: '100.000000',
};

describe('PositionsPage', () => {
  beforeEach(() => {
    resetAuthClient();
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders positions list, summary, and allocation on happy path', async () => {
    const restore = installFetch((url) => {
      if (url.includes('/api/v1/positions')) {
        return {
          status: 200,
          body: { data: [POSITION], total: 1, has_more: false },
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
                added_at: '2026-04-01T00:00:00Z',
                last_refresh_at: '2026-04-17T21:00:00Z',
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
      renderPositions();
      await waitFor(() => {
        expect(screen.getByTestId('positions-list')).toBeInTheDocument();
      });
      // AAPL renders in both the allocation legend AND the position row.
      expect(screen.getAllByText('AAPL').length).toBeGreaterThan(0);
      expect(screen.getByText('總市值')).toBeInTheDocument();
      expect(screen.getByTestId('allocation-pie')).toBeInTheDocument();
    } finally {
      restore();
    }
  });

  it('shows empty state when there are no positions', async () => {
    const restore = installFetch((url) => {
      if (url.includes('/api/v1/positions')) {
        return { status: 200, body: { data: [], total: 0, has_more: false } };
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
      renderPositions();
      await waitFor(() => {
        expect(screen.getByText('目前沒有開倉中的持倉。')).toBeInTheDocument();
      });
      expect(screen.getByTestId('allocation-empty')).toBeInTheDocument();
    } finally {
      restore();
    }
  });

  it('opens the new-position modal when the button is clicked', async () => {
    const restore = installFetch((url) => {
      if (url.includes('/api/v1/positions')) {
        return { status: 200, body: { data: [], total: 0, has_more: false } };
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
      renderPositions();
      // Wait for initial load to finish.
      await waitFor(() => {
        expect(screen.getByText('目前沒有開倉中的持倉。')).toBeInTheDocument();
      });
      const user = userEvent.setup();
      await user.click(screen.getByRole('button', { name: '開新持倉' }));
      await waitFor(() => {
        expect(screen.getByRole('dialog')).toBeInTheDocument();
      });
    } finally {
      restore();
    }
  });
});
