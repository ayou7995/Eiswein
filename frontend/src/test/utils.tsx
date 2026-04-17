import type { ReactElement, ReactNode } from 'react';
import { render, type RenderOptions, type RenderResult } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { AuthProvider, type AuthStatus } from '../hooks/useAuth';
import type { CurrentUser } from '../api/auth';

export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: 0, gcTime: 0 },
      mutations: { retry: false },
    },
  });
}

export interface AllProvidersProps {
  children: ReactNode;
  routerInitialEntries?: string[];
  queryClient?: QueryClient;
  initialStatus?: AuthStatus;
  initialUser?: CurrentUser | null;
}

export function AllProviders({
  children,
  routerInitialEntries = ['/'],
  queryClient,
  initialStatus,
  initialUser,
}: AllProvidersProps): JSX.Element {
  const client = queryClient ?? makeQueryClient();
  const resolvedStatus: AuthStatus = initialStatus ?? 'unauthenticated';
  const resolvedUser: CurrentUser | null = initialUser ?? null;
  return (
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={routerInitialEntries}>
        <AuthProvider initialStatus={resolvedStatus} initialUser={resolvedUser}>
          {children}
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

export interface CustomRenderOptions extends Omit<RenderOptions, 'wrapper'> {
  routerInitialEntries?: string[];
  queryClient?: QueryClient;
  initialStatus?: AuthStatus;
  initialUser?: CurrentUser | null;
}

export function renderWithProviders(
  ui: ReactElement,
  options: CustomRenderOptions = {},
): RenderResult {
  const {
    routerInitialEntries,
    queryClient,
    initialStatus,
    initialUser,
    ...rtlOptions
  } = options;
  return render(ui, {
    wrapper: ({ children }) => (
      <AllProviders
        {...(routerInitialEntries ? { routerInitialEntries } : {})}
        {...(queryClient ? { queryClient } : {})}
        {...(initialStatus ? { initialStatus } : {})}
        {...(initialUser !== undefined ? { initialUser } : {})}
      >
        {children}
      </AllProviders>
    ),
    ...rtlOptions,
  });
}
