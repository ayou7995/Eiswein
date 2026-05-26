import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { AuthProvider } from '../hooks/useAuth';
import { resetAuthClient } from '../api/client';

vi.mock('lightweight-charts', () => {
  const makeSeries = (): unknown => ({
    setData: vi.fn(),
    applyOptions: vi.fn(),
  });
  const chart = {
    addCandlestickSeries: vi.fn(makeSeries),
    addHistogramSeries: vi.fn(makeSeries),
    addLineSeries: vi.fn(makeSeries),
    addAreaSeries: vi.fn(makeSeries),
    priceScale: vi.fn(() => ({ applyOptions: vi.fn() })),
    timeScale: vi.fn(() => ({ fitContent: vi.fn() })),
    applyOptions: vi.fn(),
    remove: vi.fn(),
  };
  return {
    createChart: vi.fn(() => chart),
    ColorType: { Solid: 'solid' },
    LineStyle: { Solid: 0, Dashed: 1 },
  };
});

import { TickerDetailPage } from './TickerDetailPage';

type Handler = (url: string) => { status: number; body: unknown };

function installFetch(handler: Handler): () => void {
  const original = globalThis.fetch;
  const mock = vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === 'string' ? input : input.toString();
    const { status, body } = handler(url);
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

function renderPage(symbol: string): void {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 0, gcTime: 0 } },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/ticker/${symbol}`]}>
        <AuthProvider
          initialStatus="authenticated"
          initialUser={{ username: 'admin', is_admin: true }}
        >
          <Routes>
            <Route path="/ticker/:symbol" element={<TickerDetailPage />} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function indicatorSeries(name: string): { status: number; body: unknown } {
  return {
    status: 200,
    body: {
      indicator: name,
      series: [],
      summary_zh: '資料準備中',
    },
  };
}

describe('TickerDetailPage', () => {
  beforeEach(() => {
    resetAuthClient();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders signal + indicators + chart on happy path', async () => {
    const restore = installFetch((url) => {
      if (url.includes('/ticker/AAPL/signal')) {
        return {
          status: 200,
          body: {
            symbol: 'AAPL',
            date: '2026-04-17',
            timezone: 'America/New_York',
            action: 'buy',
            action_label: '買入 🟢',
            direction_green_count: 3,
            direction_red_count: 1,
            timing_modifier: 'favorable',
            timing_badge: '✓ 時機好',
            show_timing_modifier: true,
            entry_tiers: {
              aggressive: '180.00',
              ideal: '175.00',
              conservative: '170.00',
              split_suggestion: [30, 40, 30],
            },
            stop_loss: '160.00',
            market_posture_at_compute: 'normal',
            pros_cons: [
              {
                category: 'direction',
                tone: 'pro',
                short_label: '站上 50/200 MA',
                detail: { ma50: 170.2, ma200: 160.5 },
                indicator_name: 'price_vs_ma',
                timeframe: 'mid',
              },
            ],
            indicator_version: '1.0.0',
            computed_at: '2026-04-17T21:30:00Z',
          },
        };
      }
      if (url.includes('/ticker/AAPL/indicators')) {
        return {
          status: 200,
          body: {
            symbol: 'AAPL',
            date: '2026-04-17',
            timezone: 'America/New_York',
            indicator_version: '1.0.0',
            indicators: {
              price_vs_ma: {
                name: 'price_vs_ma',
                value: 1.5,
                signal: 'green',
                data_sufficient: true,
                short_label: '站上 50/200 MA',
                detail: { ma50: 170, ma200: 160 },
                indicator_version: '1.0.0',
              },
              rsi: {
                name: 'rsi',
                value: 62,
                signal: 'green',
                data_sufficient: true,
                short_label: 'RSI 62',
                detail: { rsi: 62 },
                indicator_version: '1.0.0',
              },
              volume_anomaly: {
                name: 'volume_anomaly',
                value: 1.1,
                signal: 'yellow',
                data_sufficient: true,
                short_label: '成交量平穩',
                detail: {},
                indicator_version: '1.0.0',
              },
              relative_strength: {
                name: 'relative_strength',
                value: 1.05,
                signal: 'green',
                data_sufficient: true,
                short_label: '優於 SPX',
                detail: {},
                indicator_version: '1.0.0',
              },
              macd: {
                name: 'macd',
                value: 0.5,
                signal: 'green',
                data_sufficient: true,
                short_label: 'MACD 多頭交叉',
                detail: {},
                indicator_version: '1.0.0',
              },
              bollinger: {
                name: 'bollinger',
                value: 0.2,
                signal: 'yellow',
                data_sufficient: true,
                short_label: '中軌徘徊',
                detail: {},
                indicator_version: '1.0.0',
              },
            },
          },
        };
      }
      if (url.includes('/ticker/AAPL/prices')) {
        return {
          status: 200,
          body: {
            symbol: 'AAPL',
            range: '6M',
            timezone: 'America/New_York',
            bars: [
              {
                date: '2026-04-17',
                open: 172,
                high: 175,
                low: 171,
                close: 174.5,
                volume: 50_000_000,
              },
            ],
          },
        };
      }
      if (url.includes('/history/signal-accuracy')) {
        return {
          status: 200,
          body: {
            symbol: 'AAPL',
            horizon: 20,
            total_signals: 0,
            correct: 0,
            accuracy_pct: 0,
            by_action: {},
            baseline: { total: 0, spy_up_count: 0, spy_up_pct: 0 },
          },
        };
      }
      if (url.includes('/history/ticker-signals')) {
        return { status: 200, body: { symbol: 'AAPL', data: [] } };
      }
      if (url.includes('/indicator/price_vs_ma/series')) return indicatorSeries('price_vs_ma');
      if (url.includes('/indicator/rsi/series')) return indicatorSeries('rsi');
      if (url.includes('/indicator/macd/series')) return indicatorSeries('macd');
      if (url.includes('/indicator/bollinger/series')) return indicatorSeries('bollinger');
      if (url.includes('/indicator/volume_anomaly/series')) return indicatorSeries('volume_anomaly');
      if (url.includes('/indicator/relative_strength/series')) return indicatorSeries('relative_strength');
      if (url.includes('/market/indicator/dxy/series')) {
        return {
          status: 200,
          body: {
            indicator: 'dxy',
            series: [],
            summary_zh: '',
            current: {
              level: 100,
              ma20: 100,
              streak_rising: false,
              streak_falling: false,
              streak_days: 0,
              ma20_change_5d: 0,
            },
          },
        };
      }
      if (url.includes('/market/indicator/fed_rate/series')) {
        return {
          status: 200,
          body: {
            indicator: 'fed_rate',
            series: [],
            summary_zh: '',
            current: {
              current_rate: 5,
              prior_30d_rate: 5,
              delta_30d: 0,
              days_since_last_change: null,
              last_change_date: null,
              last_change_direction: null,
            },
          },
        };
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    try {
      renderPage('AAPL');
      await waitFor(() => {
        expect(screen.getByRole('heading', { name: 'AAPL' })).toBeInTheDocument();
      });
      await waitFor(() => {
        const matches = screen.getAllByText(/站上 50\/200 MA/);
        expect(matches.length).toBeGreaterThanOrEqual(1);
      });
      // Timing modifier badge flows through the ActionBadge.
      expect(screen.getByTestId('action-badge-timing')).toHaveTextContent('✓ 時機好');
      expect(screen.getByTestId('range-6M')).toHaveAttribute('aria-checked', 'true');
      // Stop loss reference (Sherry-style 200MA × 0.97) shown in header
      // with the formula on a hover tooltip.
      expect(screen.getByTestId('stop-loss-pill')).toBeInTheDocument();
      // All 4 direction indicator cards render inline (no collapse).
      expect(screen.getByTestId('indicator-card-rsi')).toBeInTheDocument();
      expect(screen.getByTestId('indicator-card-price_vs_ma')).toBeInTheDocument();
    } finally {
      restore();
    }
  });

  it('shows 分析運算中 when the signal is not yet available', async () => {
    const restore = installFetch((url) => {
      if (url.includes('/ticker/AAPL/signal')) {
        return {
          status: 404,
          body: {
            error: {
              code: 'not_found',
              message: 'Signal unavailable',
              details: { reason: 'signal_unavailable' },
            },
          },
        };
      }
      if (url.includes('/ticker/AAPL/indicators')) {
        return {
          status: 404,
          body: {
            error: {
              code: 'not_found',
              message: 'No indicators',
              details: { reason: 'indicators_unavailable' },
            },
          },
        };
      }
      if (url.includes('/ticker/AAPL/prices')) {
        return {
          status: 200,
          body: {
            symbol: 'AAPL',
            range: '6M',
            timezone: 'America/New_York',
            bars: [],
          },
        };
      }
      if (url.includes('/history/signal-accuracy')) {
        return {
          status: 200,
          body: {
            symbol: 'AAPL',
            horizon: 20,
            total_signals: 0,
            correct: 0,
            accuracy_pct: 0,
            by_action: {},
            baseline: { total: 0, spy_up_count: 0, spy_up_pct: 0 },
          },
        };
      }
      if (url.includes('/history/ticker-signals')) {
        return { status: 200, body: { symbol: 'AAPL', data: [] } };
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    try {
      renderPage('AAPL');
      await waitFor(() => {
        expect(screen.getByText('分析運算中')).toBeInTheDocument();
      });
      // Three indicator groups (方向 / 時機 / 總經) each render the
      // pending message inline now that <details> wrappers are gone.
      expect(
        screen.getAllByText('尚無指標資料，請待下一次每日運算。').length,
      ).toBeGreaterThanOrEqual(1);
    } finally {
      restore();
    }
  });
});
