import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import { configureAuthClient } from '../api/client';
import {
  getCurrentUser,
  login as loginRequest,
  logout as logoutRequest,
  refreshToken,
  type CurrentUser,
} from '../api/auth';

export type AuthStatus = 'loading' | 'authenticated' | 'unauthenticated';

export interface AuthContextValue {
  status: AuthStatus;
  user: CurrentUser | null;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  // Exposed mainly for tests so they can force a known state without hitting
  // the network. Not used by production pages.
  setUnauthenticated: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export interface AuthProviderProps {
  children: ReactNode;
  // Starting status override — tests use 'unauthenticated' or 'authenticated'
  // to skip the initial /api/v1/me probe.
  initialStatus?: AuthStatus;
  initialUser?: CurrentUser | null;
}

export function AuthProvider({
  children,
  initialStatus = 'loading',
  initialUser = null,
}: AuthProviderProps): JSX.Element {
  const [status, setStatus] = useState<AuthStatus>(initialStatus);
  const [user, setUser] = useState<CurrentUser | null>(initialUser);

  const handleUnauthorized = useCallback(() => {
    setUser(null);
    setStatus('unauthenticated');
  }, []);

  // Register refresh + unauthorized hooks with the fetch wrapper so every
  // request can reuse the same single-flight refresh strategy.
  useEffect(() => {
    configureAuthClient({
      refresh: async () => {
        await refreshToken();
      },
      onUnauthorized: handleUnauthorized,
    });
  }, [handleUnauthorized]);

  // On mount: probe /api/v1/me to see if we already have a valid cookie. If
  // the endpoint isn't ready yet in Phase 0, a 404 will correctly fall back
  // to unauthenticated via the parseErrorEnvelope path.
  useEffect(() => {
    if (initialStatus !== 'loading') {
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const me = await getCurrentUser();
        if (!cancelled) {
          setUser(me);
          setStatus('authenticated');
        }
      } catch {
        if (!cancelled) {
          setUser(null);
          setStatus('unauthenticated');
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [initialStatus]);

  const login = useCallback(async (username: string, password: string): Promise<void> => {
    const response = await loginRequest(username, password);
    setUser(response.user);
    setStatus('authenticated');
  }, []);

  const logout = useCallback(async (): Promise<void> => {
    try {
      await logoutRequest();
    } finally {
      setUser(null);
      setStatus('unauthenticated');
    }
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      status,
      user,
      login,
      logout,
      setUnauthenticated: handleUnauthorized,
    }),
    [status, user, login, logout, handleUnauthorized],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return ctx;
}
