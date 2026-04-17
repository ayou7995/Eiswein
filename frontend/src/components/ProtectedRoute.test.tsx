import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider } from '../hooks/useAuth';
import { ProtectedRoute } from './ProtectedRoute';

function TestHarness({
  status,
}: {
  status: 'authenticated' | 'unauthenticated' | 'loading';
}): JSX.Element {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/secret']}>
        <AuthProvider
          initialStatus={status}
          initialUser={status === 'authenticated' ? { username: 'admin', is_admin: true } : null}
        >
          <Routes>
            <Route path="/login" element={<div>login-page</div>} />
            <Route
              path="/secret"
              element={
                <ProtectedRoute>
                  <div>secret-content</div>
                </ProtectedRoute>
              }
            />
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe('ProtectedRoute', () => {
  it('renders children when authenticated', () => {
    render(<TestHarness status="authenticated" />);
    expect(screen.getByText('secret-content')).toBeInTheDocument();
  });

  it('redirects to /login when unauthenticated', () => {
    render(<TestHarness status="unauthenticated" />);
    expect(screen.getByText('login-page')).toBeInTheDocument();
    expect(screen.queryByText('secret-content')).not.toBeInTheDocument();
  });

  it('shows a loading indicator while auth status is resolving', () => {
    render(<TestHarness status="loading" />);
    expect(screen.getByRole('status')).toHaveAccessibleName('驗證登入狀態…');
  });
});
