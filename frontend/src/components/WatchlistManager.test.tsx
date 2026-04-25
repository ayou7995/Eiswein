import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { WatchlistManager } from './WatchlistManager';
import { renderWithProviders } from '../test/utils';
import { EisweinApiError } from '../api/errors';
import type { WatchlistItem, WatchlistListResult } from '../api/watchlist';
import type { Job } from '../api/jobs';

vi.mock('../hooks/useWatchlist', () => ({
  useWatchlist: vi.fn(),
  useAddTicker: vi.fn(),
  useRemoveTicker: vi.fn(),
  useTickerStatusPolling: vi.fn(),
}));

vi.mock('../hooks/useJob', () => ({
  useJob: vi.fn(),
  useCancelJob: vi.fn(),
  jobQueryKey: (id: number | null) => ['job', id ?? 'none'],
  JOB_QUERY_KEY_ROOT: ['job'],
}));

import {
  useAddTicker,
  useRemoveTicker,
  useWatchlist,
} from '../hooks/useWatchlist';
import { useCancelJob, useJob } from '../hooks/useJob';

const mockUseWatchlist = vi.mocked(useWatchlist);
const mockUseAddTicker = vi.mocked(useAddTicker);
const mockUseRemoveTicker = vi.mocked(useRemoveTicker);
const mockUseJob = vi.mocked(useJob);
const mockUseCancelJob = vi.mocked(useCancelJob);

function makeItem(overrides: Partial<WatchlistItem> = {}): WatchlistItem {
  return {
    symbol: 'NVDA',
    dataStatus: 'ready',
    addedAt: new Date('2026-04-01T00:00:00Z'),
    lastRefreshAt: new Date('2026-04-21T21:00:00Z'),
    isSystem: false,
    activeOnboardingJobId: null,
    ...overrides,
  };
}

function makeWatchlistQuery(items: WatchlistItem[], overrides: Record<string, unknown> = {}) {
  const result: WatchlistListResult = {
    data: items,
    total: items.length,
    hasMore: false,
  };
  return {
    data: result,
    isLoading: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
    ...overrides,
  } as unknown as ReturnType<typeof useWatchlist>;
}

function makeMutation<T>(overrides: Record<string, unknown> = {}): T {
  return {
    mutateAsync: vi.fn().mockResolvedValue(undefined),
    isPending: false,
    isError: false,
    error: null,
    reset: vi.fn(),
    ...overrides,
  } as unknown as T;
}

function makeJob(overrides: Partial<Job> = {}): Job {
  return {
    id: 11,
    kind: 'onboarding',
    symbol: 'NVDA',
    from_date: '2025-01-01',
    to_date: '2026-04-22',
    state: 'running',
    force: false,
    processed_days: 228,
    total_days: 506,
    skipped_existing_days: 0,
    failed_days: 0,
    started_at: '2026-04-22T00:00:00Z',
    finished_at: null,
    error: null,
    created_at: '2026-04-22T00:00:00Z',
    created_by_user_id: 1,
    cancel_requested: false,
    ...overrides,
  };
}

function makeJobQuery(data: Job | undefined) {
  return {
    data,
    isLoading: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
  } as unknown as ReturnType<typeof useJob>;
}

beforeEach(() => {
  mockUseAddTicker.mockReturnValue(
    makeMutation<ReturnType<typeof useAddTicker>>(),
  );
  mockUseRemoveTicker.mockReturnValue(
    makeMutation<ReturnType<typeof useRemoveTicker>>(),
  );
  mockUseCancelJob.mockReturnValue(
    makeMutation<ReturnType<typeof useCancelJob>>(),
  );
  mockUseJob.mockReturnValue(makeJobQuery(undefined));
});

afterEach(() => {
  vi.clearAllMocks();
});

describe('WatchlistManager — add flow', () => {
  it('submits a valid ticker and clears the input on success', async () => {
    const user = userEvent.setup();
    mockUseWatchlist.mockReturnValue(makeWatchlistQuery([]));
    const mutateAsync = vi.fn().mockResolvedValue({
      data: makeItem({ symbol: 'AAPL', dataStatus: 'pending', activeOnboardingJobId: 99 }),
      jobId: 99,
    });
    mockUseAddTicker.mockReturnValue(
      makeMutation<ReturnType<typeof useAddTicker>>({ mutateAsync }),
    );

    renderWithProviders(<WatchlistManager />);
    await user.type(screen.getByLabelText('輸入股票代碼'), 'AAPL');
    await user.click(screen.getByRole('button', { name: '加入' }));

    await waitFor(() => {
      expect(mutateAsync).toHaveBeenCalledWith('AAPL');
    });
    await waitFor(() => {
      expect((screen.getByLabelText('輸入股票代碼') as HTMLInputElement).value).toBe('');
    });
    expect(screen.getByText(/已加入 AAPL/)).toBeInTheDocument();
  });

  it('shows invalid_ticker error message inline', async () => {
    const user = userEvent.setup();
    mockUseWatchlist.mockReturnValue(makeWatchlistQuery([]));
    const mutateAsync = vi
      .fn()
      .mockRejectedValue(new EisweinApiError(400, 'invalid_ticker', '此股票代碼無效'));
    mockUseAddTicker.mockReturnValue(
      makeMutation<ReturnType<typeof useAddTicker>>({ mutateAsync }),
    );

    renderWithProviders(<WatchlistManager />);
    await user.type(screen.getByLabelText('輸入股票代碼'), 'XXX');
    await user.click(screen.getByRole('button', { name: '加入' }));

    await waitFor(() => {
      expect(screen.getByTestId('watchlist-add-error')).toHaveTextContent(
        'XXX 不是有效股票代碼',
      );
    });
  });

  it('maps 503 preflight_unavailable to a network error message', async () => {
    const user = userEvent.setup();
    mockUseWatchlist.mockReturnValue(makeWatchlistQuery([]));
    const mutateAsync = vi
      .fn()
      .mockRejectedValue(
        new EisweinApiError(503, 'preflight_unavailable', 'Upstream error'),
      );
    mockUseAddTicker.mockReturnValue(
      makeMutation<ReturnType<typeof useAddTicker>>({ mutateAsync }),
    );

    renderWithProviders(<WatchlistManager />);
    await user.type(screen.getByLabelText('輸入股票代碼'), 'AAPL');
    await user.click(screen.getByRole('button', { name: '加入' }));

    await waitFor(() => {
      expect(screen.getByTestId('watchlist-add-error')).toHaveTextContent(
        '網路錯誤，請稍後重試',
      );
    });
  });
});

describe('WatchlistManager — SPY system row', () => {
  it('renders SPY without a delete button', () => {
    mockUseWatchlist.mockReturnValue(
      makeWatchlistQuery([makeItem({ symbol: 'SPY', isSystem: true })]),
    );

    renderWithProviders(<WatchlistManager />);

    expect(screen.getByText('SPY')).toBeInTheDocument();
    expect(screen.getByText('系統基準')).toBeInTheDocument();
    // No "移除 SPY" / "×" action is rendered.
    expect(screen.queryByRole('button', { name: /移除 SPY/ })).toBeNull();
  });
});

describe('WatchlistManager — pending row', () => {
  it('renders a progress bar and % from the polled job', () => {
    mockUseWatchlist.mockReturnValue(
      makeWatchlistQuery([
        makeItem({ symbol: 'NVDA', dataStatus: 'pending', activeOnboardingJobId: 11 }),
      ]),
    );
    mockUseJob.mockReturnValue(makeJobQuery(makeJob()));

    renderWithProviders(<WatchlistManager />);

    // 228 / 506 = 45%
    expect(screen.getByText(/45% \(228\/506 天\)/)).toBeInTheDocument();
    const progressbar = screen.getByRole('progressbar', { name: /NVDA 下載進度/ });
    expect(progressbar).toHaveAttribute('aria-valuenow', '228');
    expect(progressbar).toHaveAttribute('aria-valuemax', '506');
  });

  it('opens the cancel confirm modal and calls cancel + remove on confirm', async () => {
    const user = userEvent.setup();
    mockUseWatchlist.mockReturnValue(
      makeWatchlistQuery([
        makeItem({ symbol: 'NVDA', dataStatus: 'pending', activeOnboardingJobId: 11 }),
      ]),
    );
    mockUseJob.mockReturnValue(makeJobQuery(makeJob()));
    const cancelMutate = vi.fn().mockResolvedValue(makeJob({ cancel_requested: true }));
    const removeMutate = vi.fn().mockResolvedValue({ ok: true });
    mockUseCancelJob.mockReturnValue(
      makeMutation<ReturnType<typeof useCancelJob>>({ mutateAsync: cancelMutate }),
    );
    mockUseRemoveTicker.mockReturnValue(
      makeMutation<ReturnType<typeof useRemoveTicker>>({ mutateAsync: removeMutate }),
    );

    renderWithProviders(<WatchlistManager />);
    await user.click(screen.getByRole('button', { name: /取消加入 NVDA/ }));

    await waitFor(() => {
      expect(screen.getByRole('dialog')).toBeInTheDocument();
    });
    await user.click(screen.getByRole('button', { name: '取消加入' }));

    await waitFor(() => {
      expect(cancelMutate).toHaveBeenCalledWith(11);
    });
    await waitFor(() => {
      expect(removeMutate).toHaveBeenCalledWith('NVDA');
    });
  });
});

describe('WatchlistManager — ready row delete confirmation', () => {
  it('inline prompts confirmation, then calls removeFromWatchlist', async () => {
    const user = userEvent.setup();
    mockUseWatchlist.mockReturnValue(
      makeWatchlistQuery([makeItem({ symbol: 'TSLA' })]),
    );
    const mutateAsync = vi.fn().mockResolvedValue({ ok: true });
    mockUseRemoveTicker.mockReturnValue(
      makeMutation<ReturnType<typeof useRemoveTicker>>({ mutateAsync }),
    );

    renderWithProviders(<WatchlistManager />);
    await user.click(screen.getByRole('button', { name: /移除 TSLA/ }));
    await user.click(screen.getByRole('button', { name: '是' }));

    await waitFor(() => {
      expect(mutateAsync).toHaveBeenCalledWith('TSLA');
    });
  });
});

describe('WatchlistManager — failed row', () => {
  it('renders retry + remove and a 加入失敗 badge', () => {
    mockUseWatchlist.mockReturnValue(
      makeWatchlistQuery([makeItem({ symbol: 'XYZ', dataStatus: 'failed' })]),
    );

    renderWithProviders(<WatchlistManager />);
    expect(screen.getByText(/加入失敗/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /重試加入 XYZ/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /移除 XYZ/ })).toBeInTheDocument();
  });

  it('greys out delisted and hides retry', () => {
    mockUseWatchlist.mockReturnValue(
      makeWatchlistQuery([makeItem({ symbol: 'OLD', dataStatus: 'delisted' })]),
    );

    renderWithProviders(<WatchlistManager />);
    expect(screen.getByText(/已下市/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /重試加入 OLD/ })).toBeNull();
    expect(screen.getByRole('button', { name: /移除 OLD/ })).toBeInTheDocument();
  });
});
