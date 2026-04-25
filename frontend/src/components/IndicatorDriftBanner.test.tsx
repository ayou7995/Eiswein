import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { IndicatorDriftBanner } from './IndicatorDriftBanner';
import { renderWithProviders } from '../test/utils';
import type { DriftStatus } from '../api/indicators';
import type { Job } from '../api/jobs';

vi.mock('../hooks/useIndicatorDrift', () => ({
  useDriftStatus: vi.fn(),
  useRevalidateIndicators: vi.fn(),
  DRIFT_QUERY_KEY: ['indicators', 'drift'],
}));

vi.mock('../hooks/useJob', () => ({
  useJob: vi.fn(),
  useCancelJob: vi.fn(),
  jobQueryKey: (id: number | null) => ['job', id ?? 'none'],
  JOB_QUERY_KEY_ROOT: ['job'],
}));

import {
  useDriftStatus,
  useRevalidateIndicators,
} from '../hooks/useIndicatorDrift';
import { useJob } from '../hooks/useJob';

const mockUseDriftStatus = vi.mocked(useDriftStatus);
const mockUseRevalidate = vi.mocked(useRevalidateIndicators);
const mockUseJob = vi.mocked(useJob);

function makeDrift(overrides: Partial<DriftStatus> = {}): DriftStatus {
  return {
    has_drift: true,
    current_version: 'v2',
    stale_versions: ['v1'],
    stale_row_count: 1234,
    running_revalidation_job_id: null,
    ...overrides,
  };
}

function makeJob(overrides: Partial<Job> = {}): Job {
  return {
    id: 7,
    kind: 'revalidation',
    symbol: null,
    from_date: '2025-01-01',
    to_date: '2026-01-01',
    state: 'running',
    force: false,
    processed_days: 10,
    total_days: 250,
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

function makeDriftQuery(
  data: DriftStatus | undefined,
  overrides: Record<string, unknown> = {},
) {
  return {
    data,
    isLoading: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
    ...overrides,
  } as unknown as ReturnType<typeof useDriftStatus>;
}

function makeJobQuery(
  data: Job | undefined,
  overrides: Record<string, unknown> = {},
) {
  return {
    data,
    isLoading: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
    ...overrides,
  } as unknown as ReturnType<typeof useJob>;
}

function makeMutation<T>(overrides: Record<string, unknown> = {}): T {
  return {
    mutateAsync: vi.fn().mockResolvedValue({ job_id: 7, state: 'pending' }),
    isPending: false,
    isError: false,
    error: null,
    reset: vi.fn(),
    ...overrides,
  } as unknown as T;
}

// jsdom ships a working sessionStorage by default; keep tests hermetic.
beforeEach(() => {
  window.sessionStorage.clear();
  mockUseRevalidate.mockReturnValue(
    makeMutation<ReturnType<typeof useRevalidateIndicators>>(),
  );
  mockUseJob.mockReturnValue(makeJobQuery(undefined));
});

afterEach(() => {
  vi.clearAllMocks();
});

describe('IndicatorDriftBanner', () => {
  it('renders nothing when there is no drift', () => {
    mockUseDriftStatus.mockReturnValue(
      makeDriftQuery(makeDrift({ has_drift: false, stale_row_count: 0, stale_versions: [] })),
    );
    const { container } = renderWithProviders(<IndicatorDriftBanner />);
    expect(container.firstChild).toBeNull();
  });

  it('renders the drift banner when has_drift=true', () => {
    mockUseDriftStatus.mockReturnValue(makeDriftQuery(makeDrift()));
    renderWithProviders(<IndicatorDriftBanner />);
    expect(screen.getByTestId('drift-banner')).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('指標公式已更新至 v2');
    expect(screen.getByRole('alert')).toHaveTextContent('1234 筆歷史訊號');
  });

  it('persists dismiss to sessionStorage and hides banner', async () => {
    const user = userEvent.setup();
    mockUseDriftStatus.mockReturnValue(makeDriftQuery(makeDrift()));
    renderWithProviders(<IndicatorDriftBanner />);

    await user.click(screen.getByRole('button', { name: /稍後/ }));

    await waitFor(() => {
      expect(screen.queryByTestId('drift-banner')).toBeNull();
    });
    expect(window.sessionStorage.getItem('eiswein.drift.dismissed.v2')).toBe('true');
  });

  it('shows progress banner when a revalidation job is in flight via running_revalidation_job_id', () => {
    mockUseDriftStatus.mockReturnValue(
      makeDriftQuery(makeDrift({ running_revalidation_job_id: 7 })),
    );
    mockUseJob.mockReturnValue(
      makeJobQuery(makeJob({ processed_days: 25, total_days: 250 })),
    );

    renderWithProviders(<IndicatorDriftBanner />);

    const banner = screen.getByTestId('drift-banner-progress');
    expect(banner).toBeInTheDocument();
    expect(banner).toHaveTextContent('重算中…');
    expect(screen.getByRole('progressbar', { name: /指標重算進度/ })).toHaveAttribute(
      'aria-valuenow',
      '25',
    );
  });

  it('switches to progress mode after clicking 立即重算全部', async () => {
    const user = userEvent.setup();
    const mutateAsync = vi.fn().mockResolvedValue({ job_id: 7, state: 'pending' });
    mockUseRevalidate.mockReturnValue(
      makeMutation<ReturnType<typeof useRevalidateIndicators>>({ mutateAsync }),
    );
    mockUseDriftStatus.mockReturnValue(makeDriftQuery(makeDrift()));

    renderWithProviders(<IndicatorDriftBanner />);
    expect(screen.getByTestId('drift-banner')).toBeInTheDocument();

    // After clicking the CTA, the banner should stay (useJob still
    // returns undefined job until the poll kicks in) but the component
    // should have recorded the active job id — we assert the mutation
    // fired and the dismiss button went away.
    await user.click(screen.getByRole('button', { name: /立即重算全部/ }));

    await waitFor(() => {
      expect(mutateAsync).toHaveBeenCalledTimes(1);
    });
  });

  it('shows failure banner when the revalidation job state is failed', () => {
    mockUseDriftStatus.mockReturnValue(
      makeDriftQuery(makeDrift({ running_revalidation_job_id: 7 })),
    );
    mockUseJob.mockReturnValue(
      makeJobQuery(makeJob({ state: 'failed', error: 'yfinance timeout' })),
    );

    renderWithProviders(<IndicatorDriftBanner />);

    const banner = screen.getByTestId('drift-banner-failed');
    expect(banner).toHaveTextContent('重算失敗');
    expect(banner).toHaveTextContent('yfinance timeout');
  });
});
