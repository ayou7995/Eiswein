import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider } from '../hooks/useAuth';
import { resetAuthClient } from '../api/client';
import { LoginPage } from './LoginPage';
import { render } from '@testing-library/react';

interface FetchScript {
  status: number;
  body: unknown;
}

function installFetch(scripts: FetchScript[]): () => void {
  const queue = [...scripts];
  const mock = vi.fn(async () => {
    const next = queue.shift();
    if (!next) {
      throw new Error('unexpected fetch call');
    }
    return new Response(JSON.stringify(next.body), {
      status: next.status,
      headers: { 'content-type': 'application/json' },
    });
  });
  const original = globalThis.fetch;
  globalThis.fetch = mock as unknown as typeof fetch;
  return () => {
    globalThis.fetch = original;
  };
}

function renderLogin(): void {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/login']}>
        <AuthProvider initialStatus="unauthenticated" initialUser={null}>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/dashboard" element={<div>dashboard-page</div>} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('LoginPage', () => {
  beforeEach(() => {
    resetAuthClient();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders form with accessible password input', () => {
    const restore = installFetch([]);
    try {
      renderLogin();
      const input = screen.getByLabelText('密碼');
      expect(input).toHaveAttribute('type', 'password');
      expect(input).toHaveAttribute('autocomplete', 'current-password');
    } finally {
      restore();
    }
  });

  it('validates the required password field', async () => {
    const restore = installFetch([]);
    try {
      renderLogin();
      const user = userEvent.setup();
      await user.click(screen.getByRole('button', { name: /登入/ }));
      expect(await screen.findByRole('alert')).toHaveTextContent('請輸入密碼');
    } finally {
      restore();
    }
  });

  it('navigates to /dashboard on successful login', async () => {
    const restore = installFetch([
      { status: 200, body: { ok: true, user: { username: 'admin', is_admin: true } } },
    ]);
    try {
      renderLogin();
      const user = userEvent.setup();
      await user.type(screen.getByLabelText('密碼'), 'correct-horse');
      await user.click(screen.getByRole('button', { name: /登入/ }));
      await waitFor(() => {
        expect(screen.getByText('dashboard-page')).toBeInTheDocument();
      });
    } finally {
      restore();
    }
  });

  it('shows invalid_password message with attempts_remaining', async () => {
    const restore = installFetch([
      {
        status: 401,
        body: {
          error: {
            code: 'invalid_password',
            message: '密碼錯誤',
            details: { attempts_remaining: 3 },
          },
        },
      },
    ]);
    try {
      renderLogin();
      const user = userEvent.setup();
      await user.type(screen.getByLabelText('密碼'), 'wrong');
      await user.click(screen.getByRole('button', { name: /登入/ }));
      const alert = await screen.findByText(/密碼錯誤/);
      expect(alert).toHaveTextContent('剩餘嘗試：3');
    } finally {
      restore();
    }
  });

  it('shows locked_out message with retry_after_seconds', async () => {
    const restore = installFetch([
      {
        status: 403,
        body: {
          error: {
            code: 'locked_out',
            message: '嘗試次數過多，已暫時鎖定',
            details: { retry_after_seconds: 900 },
          },
        },
      },
    ]);
    try {
      renderLogin();
      const user = userEvent.setup();
      await user.type(screen.getByLabelText('密碼'), 'anything');
      await user.click(screen.getByRole('button', { name: /登入/ }));
      const alert = await screen.findByText(/已暫時鎖定/);
      expect(alert).toHaveTextContent('請於 900 秒後再試');
    } finally {
      restore();
    }
  });
});
