import { lazy, Suspense, type ReactNode } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import { AppShell } from './layouts/AppShell';
import { ErrorBoundary } from './components/ErrorBoundary';
import { LoadingSpinner } from './components/LoadingSpinner';
import { ProtectedRoute } from './components/ProtectedRoute';
import { LoginPage } from './pages/LoginPage';
import { ROUTES } from './lib/constants';

// Lazy-loaded pages per DoD rule 10 — keeps the initial bundle small and lets
// each page fail-closed inside its own boundary.
const DashboardPage = lazy(() =>
  import('./pages/DashboardPage').then((m) => ({ default: m.DashboardPage })),
);
const TickerDetailPage = lazy(() =>
  import('./pages/TickerDetailPage').then((m) => ({ default: m.TickerDetailPage })),
);
const PositionsPage = lazy(() =>
  import('./pages/PositionsPage').then((m) => ({ default: m.PositionsPage })),
);
const HistoryPage = lazy(() =>
  import('./pages/HistoryPage').then((m) => ({ default: m.HistoryPage })),
);
const SettingsPage = lazy(() =>
  import('./pages/SettingsPage').then((m) => ({ default: m.SettingsPage })),
);

function PageSuspense({ children }: { children: ReactNode }): JSX.Element {
  return (
    <ErrorBoundary>
      <Suspense
        fallback={
          <div className="flex min-h-[20vh] items-center justify-center">
            <LoadingSpinner label="頁面載入中…" />
          </div>
        }
      >
        {children}
      </Suspense>
    </ErrorBoundary>
  );
}

export function App(): JSX.Element {
  return (
    <Routes>
      <Route path={ROUTES.LOGIN} element={<LoginPage />} />

      <Route
        element={
          <ProtectedRoute>
            <AppShell />
          </ProtectedRoute>
        }
      >
        <Route
          path={ROUTES.DASHBOARD}
          element={
            <PageSuspense>
              <DashboardPage />
            </PageSuspense>
          }
        />
        <Route
          path={ROUTES.TICKER}
          element={
            <PageSuspense>
              <TickerDetailPage />
            </PageSuspense>
          }
        />
        <Route
          path={ROUTES.POSITIONS}
          element={
            <PageSuspense>
              <PositionsPage />
            </PageSuspense>
          }
        />
        <Route
          path={ROUTES.HISTORY}
          element={
            <PageSuspense>
              <HistoryPage />
            </PageSuspense>
          }
        />
        <Route
          path={ROUTES.SETTINGS}
          element={
            <PageSuspense>
              <SettingsPage />
            </PageSuspense>
          }
        />
      </Route>

      <Route path="/" element={<Navigate to={ROUTES.DASHBOARD} replace />} />
      <Route path="*" element={<Navigate to={ROUTES.DASHBOARD} replace />} />
    </Routes>
  );
}
