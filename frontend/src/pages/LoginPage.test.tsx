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

  it('renders form with accessible username + password inputs', () => {
    const restore = installFetch([]);
    try {
      renderLogin();
      const username = screen.getByLabelText('使用者名稱');
      expect(username).toHaveAttribute('type', 'text');
      expect(username).toHaveAttribute('autocomplete', 'username');
      const password = screen.getByLabelText('密碼');
      expect(password).toHaveAttribute('type', 'password');
      expect(password).toHaveAttribute('autocomplete', 'current-password');
    } finally {
      restore();
    }
  });

  it('toggles password visibility when the eye button is clicked', async () => {
    const restore = installFetch([]);
    try {
      renderLogin();
      const user = userEvent.setup();
      const password = screen.getByLabelText('密碼');
      expect(password).toHaveAttribute('type', 'password');

      const toggle = screen.getByRole('button', { name: '顯示密碼' });
      expect(toggle).toHaveAttribute('aria-pressed', 'false');

      await user.click(toggle);
      expect(password).toHaveAttribute('type', 'text');
      expect(screen.getByRole('button', { name: '隱藏密碼' })).toHaveAttribute(
        'aria-pressed',
        'true',
      );

      await user.click(screen.getByRole('button', { name: '隱藏密碼' }));
      expect(password).toHaveAttribute('type', 'password');
    } finally {
      restore();
    }
  });

  it('validates both required fields', async () => {
    const restore = installFetch([]);
    try {
      renderLogin();
      const user = userEvent.setup();
      await user.click(screen.getByRole('button', { name: /登入/ }));
      expect(await screen.findByText('請輸入使用者名稱')).toBeInTheDocument();
      expect(await screen.findByText('請輸入密碼')).toBeInTheDocument();
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
      await user.type(screen.getByLabelText('使用者名稱'), 'admin');
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
      await user.type(screen.getByLabelText('使用者名稱'), 'admin');
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
      await user.type(screen.getByLabelText('使用者名稱'), 'admin');
      await user.type(screen.getByLabelText('密碼'), 'anything');
      await user.click(screen.getByRole('button', { name: /登入/ }));
      const alert = await screen.findByText(/已暫時鎖定/);
      expect(alert).toHaveTextContent('請於 900 秒後再試');
    } finally {
      restore();
    }
  });
});
