import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SchwabConnectCard } from './SchwabConnectCard';
import { renderWithProviders } from '../test/utils';
import type { SchwabStatus, SchwabTestResult } from '../api/broker';

// ---------------------------------------------------------------------------
// Module mocks
// ---------------------------------------------------------------------------

// Mock the hooks so we control data without network calls or real React Query
// query functions. We keep the mutation API intact by returning the standard
// TanStack mutation shape.
vi.mock('../hooks/useSchwabConnection', () => ({
  useSchwabConnection: vi.fn(),
  useSchwabTest: vi.fn(),
  useSchwabDisconnect: vi.fn(),
}));

// Mock startSchwabOAuth so window.location.href is never mutated in jsdom.
vi.mock('../api/broker', async (importOriginal) => {
  const original = await importOriginal<typeof import('../api/broker')>();
  return {
    ...original,
    startSchwabOAuth: vi.fn(),
  };
});

import {
  useSchwabConnection,
  useSchwabTest,
  useSchwabDisconnect,
} from '../hooks/useSchwabConnection';
import { startSchwabOAuth } from '../api/broker';

const mockUseSchwabConnection = vi.mocked(useSchwabConnection);
const mockUseSchwabTest = vi.mocked(useSchwabTest);
const mockUseSchwabDisconnect = vi.mocked(useSchwabDisconnect);

// ---------------------------------------------------------------------------
// Default mutation stubs (non-pending, no-op)
// ---------------------------------------------------------------------------

function _makeMutation(overrides: Record<string, unknown> = {}) {
  return {
    mutateAsync: vi.fn().mockResolvedValue(undefined),
    isPending: false,
    isError: false,
    error: null,
    reset: vi.fn(),
    ...overrides,
  } as unknown as ReturnType<typeof useSchwabTest> &
    ReturnType<typeof useSchwabDisconnect>;
}

function _makeQuery(data: SchwabStatus | undefined, overrides: Record<string, unknown> = {}) {
  return {
    data,
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
    ...overrides,
  } as unknown as ReturnType<typeof useSchwabConnection>;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function renderCard(routerPath = '/settings') {
  mockUseSchwabTest.mockReturnValue(_makeMutation());
  mockUseSchwabDisconnect.mockReturnValue(_makeMutation());
  return renderWithProviders(<SchwabConnectCard />, {
    routerInitialEntries: [routerPath],
    initialStatus: 'authenticated',
  });
}

// ---------------------------------------------------------------------------
// 1. Disconnected state
// ---------------------------------------------------------------------------

describe('SchwabConnectCard — disconnected', () => {
  beforeEach(() => {
    mockUseSchwabConnection.mockReturnValue(
      _makeQuery({ connected: false }),
    );
  });

  it('shows the connect button', () => {
    renderCard();
    expect(screen.getByRole('button', { name: '連接 Schwab' })).toBeInTheDocument();
  });

  it('shows the descriptive hint paragraph', () => {
    renderCard();
    expect(screen.getByText(/Schwab API/)).toBeInTheDocument();
  });

  it('calls startSchwabOAuth when connect button is clicked', async () => {
    const user = userEvent.setup();
    renderCard();
    await user.click(screen.getByRole('button', { name: '連接 Schwab' }));
    expect(startSchwabOAuth).toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// 2. Connected state
// ---------------------------------------------------------------------------

const CONNECTED_STATUS: SchwabStatus = {
  connected: true,
  accounts: [{ display_id: '...1234', nickname: 'Brokerage' }],
  mkt_data_permission: 'NP',
  last_refreshed_at: new Date().toISOString(),
  last_test_at: null,
  last_test_status: null,
  last_test_latency_ms: null,
};

describe('SchwabConnectCard — connected', () => {
  beforeEach(() => {
    mockUseSchwabConnection.mockReturnValue(_makeQuery(CONNECTED_STATUS));
  });

  it('shows the account nickname', () => {
    renderCard();
    expect(screen.getByText('Brokerage')).toBeInTheDocument();
  });

  it('shows the mkt_data_permission value', () => {
    renderCard();
    expect(screen.getByText('NP')).toBeInTheDocument();
  });

  it('shows the 15-minute delay hint for NP permission', () => {
    renderCard();
    expect(screen.getByText(/延遲 15 分鐘/)).toBeInTheDocument();
  });

  it('renders the test connection button', () => {
    renderCard();
    expect(screen.getByRole('button', { name: /測試連線/ })).toBeInTheDocument();
  });

  it('renders the disconnect button', () => {
    renderCard();
    expect(screen.getByRole('button', { name: /中斷連接/ })).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// 3. Callback banner — connected
// The component reads window.location.search directly (not React Router),
// so we must set window.location before rendering.
// ---------------------------------------------------------------------------

describe('SchwabConnectCard — callback banner success', () => {
  beforeEach(() => {
    mockUseSchwabConnection.mockReturnValue(
      _makeQuery({ connected: false }),
    );
  });

  it('shows green success banner when URL has ?schwab=connected', () => {
    // Set window.location directly; jsdom allows reassigning search.
    Object.defineProperty(window, 'location', {
      value: { ...window.location, search: '?schwab=connected', href: '/settings?schwab=connected' },
      writable: true,
      configurable: true,
    });
    mockUseSchwabTest.mockReturnValue(_makeMutation());
    mockUseSchwabDisconnect.mockReturnValue(_makeMutation());
    render(<SchwabConnectCard />, {
      wrapper: ({ children }) => (
        <>{children}</>
      ),
    });
    expect(screen.getByRole('status')).toBeInTheDocument();
    expect(screen.getByText(/已成功連接 Schwab/)).toBeInTheDocument();
    // Reset
    Object.defineProperty(window, 'location', {
      value: { ...window.location, search: '', href: '/settings' },
      writable: true,
      configurable: true,
    });
  });
});

// ---------------------------------------------------------------------------
// 4. Callback banner — error with known reason
// ---------------------------------------------------------------------------

describe('SchwabConnectCard — callback banner error', () => {
  beforeEach(() => {
    mockUseSchwabConnection.mockReturnValue(
      _makeQuery({ connected: false }),
    );
    mockUseSchwabTest.mockReturnValue(_makeMutation());
    mockUseSchwabDisconnect.mockReturnValue(_makeMutation());
  });

  afterEach(() => {
    Object.defineProperty(window, 'location', {
      value: { ...window.location, search: '', href: '/settings' },
      writable: true,
      configurable: true,
    });
  });

  it('shows translated reason for invalid_grant', () => {
    Object.defineProperty(window, 'location', {
      value: { ...window.location, search: '?schwab=error&reason=invalid_grant' },
      writable: true,
      configurable: true,
    });
    render(<SchwabConnectCard />);
    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(screen.getByText(/授權碼已失效/)).toBeInTheDocument();
  });

  it('shows generic message for unknown reason', () => {
    Object.defineProperty(window, 'location', {
      value: { ...window.location, search: '?schwab=error&reason=frobnicate' },
      writable: true,
      configurable: true,
    });
    render(<SchwabConnectCard />);
    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(screen.getByText(/未知錯誤：frobnicate/)).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// 5. Test button — success
// The text is split across multiple elements, so use a function matcher.
// ---------------------------------------------------------------------------

describe('SchwabConnectCard — test button', () => {
  it('shows success result after test completes', async () => {
    const user = userEvent.setup();
    const testResult: SchwabTestResult = {
      success: true,
      latency_ms: 312,
      account_count: 1,
      mkt_data_permission: 'NP',
      error: null,
    };

    const mutateAsync = vi.fn().mockResolvedValue(testResult);
    mockUseSchwabConnection.mockReturnValue(_makeQuery(CONNECTED_STATUS));
    mockUseSchwabTest.mockReturnValue(_makeMutation({ mutateAsync }));
    mockUseSchwabDisconnect.mockReturnValue(_makeMutation());

    renderWithProviders(<SchwabConnectCard />, {
      routerInitialEntries: ['/settings'],
      initialStatus: 'authenticated',
    });

    await user.click(screen.getByRole('button', { name: /測試連線/ }));

    await waitFor(() => {
      expect(screen.getByText(/連線正常/)).toBeInTheDocument();
    });
    // These appear in the same span element as separate text nodes
    expect(screen.getByText(/312ms/)).toBeInTheDocument();
    expect(screen.getByText(/1 個帳戶/)).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// 6. Disconnect confirm flow
// Mocks must be set BEFORE rendering so React Query uses them on mount.
// ---------------------------------------------------------------------------

describe('SchwabConnectCard — disconnect flow', () => {
  it('opens confirm modal on disconnect click and fires mutation on confirm', async () => {
    const user = userEvent.setup();
    const mutateAsync = vi.fn().mockResolvedValue(undefined);

    mockUseSchwabConnection.mockReturnValue(_makeQuery(CONNECTED_STATUS));
    mockUseSchwabTest.mockReturnValue(_makeMutation());
    mockUseSchwabDisconnect.mockReturnValue(_makeMutation({ mutateAsync }));

    renderWithProviders(<SchwabConnectCard />, {
      routerInitialEntries: ['/settings'],
      initialStatus: 'authenticated',
    });

    // Click the disconnect button — modal should open
    await user.click(screen.getByRole('button', { name: /中斷連接/ }));

    await waitFor(() => {
      expect(screen.getByRole('dialog')).toBeInTheDocument();
    });

    // Click the confirm button inside the modal (rendered in portal to document.body)
    await user.click(screen.getByRole('button', { name: /確認中斷/ }));

    await waitFor(() => {
      expect(mutateAsync).toHaveBeenCalled();
    });
  });

  it('closes modal when cancel is clicked without firing disconnect', async () => {
    const user = userEvent.setup();
    const mutateAsync = vi.fn();

    mockUseSchwabConnection.mockReturnValue(_makeQuery(CONNECTED_STATUS));
    mockUseSchwabTest.mockReturnValue(_makeMutation());
    mockUseSchwabDisconnect.mockReturnValue(_makeMutation({ mutateAsync }));

    renderWithProviders(<SchwabConnectCard />, {
      routerInitialEntries: ['/settings'],
      initialStatus: 'authenticated',
    });

    await user.click(screen.getByRole('button', { name: /中斷連接/ }));
    await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: /取消/ }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(mutateAsync).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// 7. Loading / error states
// ---------------------------------------------------------------------------

describe('SchwabConnectCard — loading and error states', () => {
  it('shows loading indicator while fetching', () => {
    mockUseSchwabConnection.mockReturnValue(
      _makeQuery(undefined, { isLoading: true }),
    );
    mockUseSchwabTest.mockReturnValue(_makeMutation());
    mockUseSchwabDisconnect.mockReturnValue(_makeMutation());

    renderWithProviders(<SchwabConnectCard />, {
      routerInitialEntries: ['/settings'],
      initialStatus: 'authenticated',
    });

    expect(screen.getByText(/載入中/)).toBeInTheDocument();
  });

  it('shows error message with retry when fetch fails', async () => {
    const user = userEvent.setup();
    const refetch = vi.fn();
    mockUseSchwabConnection.mockReturnValue(
      _makeQuery(undefined, { isError: true, refetch }),
    );
    mockUseSchwabTest.mockReturnValue(_makeMutation());
    mockUseSchwabDisconnect.mockReturnValue(_makeMutation());

    renderWithProviders(<SchwabConnectCard />, {
      routerInitialEntries: ['/settings'],
      initialStatus: 'authenticated',
    });

    expect(screen.getByText(/無法載入 Schwab 連線狀態/)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /重試/ }));
    expect(refetch).toHaveBeenCalled();
  });
});
