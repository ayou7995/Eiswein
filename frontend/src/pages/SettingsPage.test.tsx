import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { AuthProvider } from '../hooks/useAuth';
import { resetAuthClient } from '../api/client';
import { SettingsPage } from './SettingsPage';

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

function renderSettings(): void {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 0, gcTime: 0 } },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/settings']}>
        <AuthProvider
          initialStatus="authenticated"
          initialUser={{ username: 'admin', is_admin: true }}
        >
          <Routes>
            <Route path="/settings" element={<SettingsPage />} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const SYSTEM_INFO = {
  db_size_bytes: 1024 * 1024 * 3, // 3 MB
  last_daily_update_at: '2026-04-17T20:00:00Z',
  last_backup_at: null,
  watchlist_count: 5,
  positions_count: 2,
  trade_count: 17,
  user_count: 1,
};

describe('SettingsPage', () => {
  beforeEach(() => {
    resetAuthClient();
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders the system info and audit log on happy path', async () => {
    const restore = installFetch((url) => {
      if (url.includes('/settings/system-info')) {
        return { status: 200, body: SYSTEM_INFO };
      }
      if (url.includes('/settings/audit-log')) {
        return {
          status: 200,
          body: {
            data: [
              {
                id: 1,
                timestamp: '2026-04-17T09:00:00Z',
                event_type: 'login_success',
                ip: '1.2.3.4',
                details: { outcome: 'ok' },
              },
            ],
            total: 1,
            has_more: false,
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
      renderSettings();
      await waitFor(() => {
        expect(screen.getByTestId('system-info')).toBeInTheDocument();
      });
      expect(screen.getByText('資料庫大小')).toBeInTheDocument();
      expect(screen.getByText('觀察標的數')).toBeInTheDocument();
      await waitFor(() => {
        expect(screen.getByText('登入成功')).toBeInTheDocument();
      });
    } finally {
      restore();
    }
  });

  it('shows an error on wrong current password', async () => {
    const user = userEvent.setup();
    const restore = installFetch((url) => {
      if (url.includes('/settings/system-info')) {
        return { status: 200, body: SYSTEM_INFO };
      }
      if (url.includes('/settings/audit-log')) {
        return {
          status: 200,
          body: { data: [], total: 0, has_more: false },
        };
      }
      if (url.endsWith('/api/v1/watchlist')) {
        return { status: 200, body: { data: [], total: 0, has_more: false } };
      }
      if (url.includes('/settings/password')) {
        return {
          status: 401,
          body: {
            error: {
              code: 'invalid_credentials',
              message: '認證失敗',
            },
          },
        };
      }
      throw new Error(`unexpected fetch ${url}`);
    });
    try {
      renderSettings();
      await waitFor(() => {
        expect(screen.getByLabelText('目前密碼')).toBeInTheDocument();
      });
      await user.type(screen.getByLabelText('目前密碼'), 'oldpass12345');
      await user.type(screen.getByLabelText('新密碼'), 'newpassword12345');
      await user.type(screen.getByLabelText('確認新密碼'), 'newpassword12345');
      await user.click(screen.getByRole('button', { name: '變更密碼' }));
      await waitFor(() => {
        expect(screen.getByText('目前密碼不正確。')).toBeInTheDocument();
      });
    } finally {
      restore();
    }
  });

  it('shows mismatched confirm password error before hitting the API', async () => {
    const user = userEvent.setup();
    const fetchCalls: string[] = [];
    const restore = installFetch((url) => {
      fetchCalls.push(url);
      if (url.includes('/settings/system-info')) {
        return { status: 200, body: SYSTEM_INFO };
      }
      if (url.includes('/settings/audit-log')) {
        return {
          status: 200,
          body: { data: [], total: 0, has_more: false },
        };
      }
      if (url.endsWith('/api/v1/watchlist')) {
        return { status: 200, body: { data: [], total: 0, has_more: false } };
      }
      throw new Error(`unexpected fetch ${url}`);
    });
    try {
      renderSettings();
      await waitFor(() => {
        expect(screen.getByLabelText('目前密碼')).toBeInTheDocument();
      });
      await user.type(screen.getByLabelText('目前密碼'), 'oldpass12345');
      await user.type(screen.getByLabelText('新密碼'), 'newpassword12345');
      await user.type(screen.getByLabelText('確認新密碼'), 'different12345');
      await user.click(screen.getByRole('button', { name: '變更密碼' }));
      await waitFor(() => {
        expect(screen.getByText('兩次輸入的新密碼不一致')).toBeInTheDocument();
      });
      // Client-side rejection — no /settings/password call happened.
      expect(fetchCalls.some((u) => u.includes('/settings/password'))).toBe(false);
    } finally {
      restore();
    }
  });
});
