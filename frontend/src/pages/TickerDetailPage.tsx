import { useMemo, useState } from 'react';
import { useParams } from 'react-router-dom';
import { CandlestickChart } from '../components/charts/CandlestickChart';
import {
  IndicatorMultiLine,
  type MultiLineDefinition,
  type MultiLineHistogram,
  type MultiLineShadedBand,
  type MultiLineSeriesRow,
} from '../components/charts/IndicatorMultiLine';
import {
  IndicatorBoundedLine,
  type BoundedLineDefinition,
  type BoundedLineThreshold,
} from '../components/charts/IndicatorBoundedLine';
import { IndicatorVolumeBars } from '../components/charts/IndicatorVolumeBars';
import { LoadingSpinner } from '../components/LoadingSpinner';
import { ActionBadge } from '../components/ActionBadge';
import { SignalBadge } from '../components/SignalBadge';
import { ProsConsList } from '../components/ProsConsList';
import { PriceBar } from '../components/PriceBar';
import { useTickerSignal } from '../hooks/useTickerSignal';
import { useTickerIndicators } from '../hooks/useTickerIndicators';
import { useTickerPrices } from '../hooks/useTickerPrices';
import { useIndicatorSeries } from '../hooks/useIndicatorSeries';
import {
  parseDecimalString,
  type TickerSignalResponse,
} from '../api/tickerSignal';
import type { IndicatorResult } from '../api/tickerIndicators';
import type { PriceRange } from '../api/tickerPrices';
import type {
  IndicatorSeriesName,
  IndicatorSeriesResponse,
} from '../api/tickerIndicatorSeries';
import { EisweinApiError } from '../api/errors';

const DIRECTION_INDICATORS = ['price_vs_ma', 'rsi', 'volume_anomaly', 'relative_strength'];
const TIMING_INDICATORS = ['macd', 'bollinger'];
const INDICATOR_TITLES: Record<string, string> = {
  price_vs_ma: '價格 vs 50/200 MA',
  rsi: 'RSI',
  volume_anomaly: '成交量異常',
  relative_strength: '相對強度',
  macd: 'MACD',
  bollinger: 'Bollinger Bands',
};

const POSTURE_LABELS: Record<string, string> = {
  offensive: '進攻',
  normal: '正常',
  defensive: '防守',
};

const INDICATOR_SERIES_NAME: Record<string, IndicatorSeriesName> = {
  price_vs_ma: 'price_vs_ma',
  rsi: 'rsi',
  macd: 'macd',
  bollinger: 'bollinger',
  volume_anomaly: 'volume_anomaly',
  relative_strength: 'relative_strength',
};

const PRICE_VS_MA_LINES: ReadonlyArray<MultiLineDefinition> = [
  { key: 'price', label: '收盤價', color: '#e2e8f0', width: 2 },
  { key: 'ma50', label: '50 MA', color: '#38bdf8', style: 'dashed', width: 2 },
  { key: 'ma200', label: '200 MA', color: '#facc15', style: 'dashed', width: 1 },
];

const RSI_LINES: ReadonlyArray<BoundedLineDefinition> = [
  { key: 'daily', label: '日 RSI', color: '#38bdf8' },
  { key: 'weekly', label: '週 RSI', color: '#a78bfa' },
];

const RSI_THRESHOLDS: ReadonlyArray<BoundedLineThreshold> = [
  { value: 30, label: '超賣', color: '#22c55e', fillBetween: 'below' },
  { value: 70, label: '超買', color: '#ef4444', fillBetween: 'above' },
];

const MACD_LINES: ReadonlyArray<MultiLineDefinition> = [
  { key: 'macd', label: 'MACD', color: '#38bdf8', width: 2 },
  { key: 'signal', label: 'Signal', color: '#facc15', width: 1 },
];

const MACD_HISTOGRAM: MultiLineHistogram = {
  key: 'histogram',
  positiveColor: '#22c55e',
  negativeColor: '#ef4444',
};

const BB_LINES: ReadonlyArray<MultiLineDefinition> = [
  { key: 'price', label: '收盤價', color: '#e2e8f0', width: 2 },
  { key: 'middle', label: '中軌（20MA）', color: '#a78bfa', style: 'dashed', width: 1 },
];

const BB_SHADED_BAND: MultiLineShadedBand = {
  upperKey: 'upper',
  lowerKey: 'lower',
  opacity: 0.18,
  color: '#38bdf8',
};

const RELATIVE_STRENGTH_LINES: ReadonlyArray<MultiLineDefinition> = [
  { key: 'ticker_pct', label: '個股累積報酬 (%)', color: '#38bdf8', width: 2 },
  {
    key: 'spx_pct',
    label: 'SPX 累積報酬 (%)',
    color: '#94a3b8',
    style: 'dashed',
    width: 1,
  },
];

export function TickerDetailPage(): JSX.Element {
  const { symbol: rawSymbol } = useParams<{ symbol: string }>();
  const symbol = rawSymbol?.toUpperCase() ?? '';
  const [range, setRange] = useState<PriceRange>('6M');

  const signalQuery = useTickerSignal(symbol);
  const indicatorsQuery = useTickerIndicators(symbol);
  const pricesQuery = useTickerPrices(symbol, range);

  const latestClose = useMemo(() => {
    const bars = pricesQuery.data?.bars ?? [];
    const last = bars[bars.length - 1];
    return last?.close ?? null;
  }, [pricesQuery.data]);

  const signal = signalQuery.data;
  const signalError = signalQuery.error;

  if (!symbol) {
    return (
      <section aria-labelledby="ticker-heading">
        <h1 id="ticker-heading" className="text-2xl font-semibold">
          標的分析
        </h1>
        <p className="mt-2 text-sm text-signal-red">缺少股票代碼。</p>
      </section>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <TickerHeader
        symbol={symbol}
        signal={signal ?? null}
        signalError={signalError instanceof Error ? signalError : null}
        signalLoading={signalQuery.isLoading}
      />

      <CandlestickChart
        bars={pricesQuery.data?.bars ?? []}
        range={range}
        onRangeChange={setRange}
        loading={pricesQuery.isLoading}
        emptyMessage={
          pricesQuery.isError ? '無法載入價格資料' : '價格資料準備中'
        }
      />

      <DirectionCard
        symbol={symbol}
        indicators={indicatorsQuery.data?.indicators ?? null}
        isLoading={indicatorsQuery.isLoading}
        error={indicatorsQuery.error instanceof Error ? indicatorsQuery.error : null}
      />

      <TimingCard
        symbol={symbol}
        indicators={indicatorsQuery.data?.indicators ?? null}
        isLoading={indicatorsQuery.isLoading}
      />

      <EntryTiersCard signal={signal ?? null} latestClose={latestClose} />
      <StopLossCard signal={signal ?? null} latestClose={latestClose} />
      <ProsConsCard signal={signal ?? null} isLoading={signalQuery.isLoading} />
    </div>
  );
}

interface TickerHeaderProps {
  symbol: string;
  signal: TickerSignalResponse | null;
  signalError: Error | null;
  signalLoading: boolean;
}

function TickerHeader({
  symbol,
  signal,
  signalError,
  signalLoading,
}: TickerHeaderProps): JSX.Element {
  const pendingSignal =
    signalError instanceof EisweinApiError && signalError.status === 404;
  return (
    <section
      aria-labelledby="ticker-heading"
      className="flex flex-col gap-3 rounded-lg border border-slate-800 bg-slate-900/60 p-4"
    >
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <h1 id="ticker-heading" className="font-mono text-2xl font-semibold">
            {symbol}
          </h1>
          {signalLoading && <LoadingSpinner label="讀取訊號…" />}
          {signal && (
            <ActionBadge action={signal.action} timingBadge={signal.timing_badge} />
          )}
          {pendingSignal && (
            <span className="text-xs text-slate-400">分析運算中</span>
          )}
        </div>
        {signal && (
          <div className="flex flex-wrap items-center gap-3 text-xs text-slate-400">
            <span>最近交易日：{signal.date}</span>
            <span>
              市場態勢：
              {POSTURE_LABELS[signal.market_posture_at_compute] ??
                signal.market_posture_at_compute}
            </span>
            <span>指標版本：{signal.indicator_version}</span>
          </div>
        )}
      </header>
    </section>
  );
}

interface IndicatorsCardProps {
  symbol: string;
  indicators: Record<string, IndicatorResult> | null;
  isLoading: boolean;
  error?: Error | null;
}

function IndicatorList({
  symbol,
  indicators,
  keys,
  emptyMessage,
}: {
  symbol: string;
  indicators: Record<string, IndicatorResult>;
  keys: readonly string[];
  emptyMessage: string;
}): JSX.Element {
  const rows = keys
    .map((key) => ({ key, result: indicators[key] }))
    .filter((row): row is { key: string; result: IndicatorResult } => !!row.result);

  if (rows.length === 0) {
    return (
      <p role="status" className="text-sm text-slate-400">
        {emptyMessage}
      </p>
    );
  }

  return (
    <ul className="flex flex-col divide-y divide-slate-800 overflow-hidden rounded-md border border-slate-800">
      {rows.map(({ key, result }) => (
        <IndicatorRow key={key} symbol={symbol} indicatorKey={key} result={result} />
      ))}
    </ul>
  );
}

interface IndicatorRowProps {
  symbol: string;
  indicatorKey: string;
  result: IndicatorResult;
}

function IndicatorRow({
  symbol,
  indicatorKey,
  result,
}: IndicatorRowProps): JSX.Element {
  const [open, setOpen] = useState(false);
  const seriesName = INDICATOR_SERIES_NAME[indicatorKey];
  const hasDetail = Object.keys(result.detail).length > 0;
  const hasChart = seriesName !== undefined;
  const expandable = hasDetail || hasChart;
  const title = INDICATOR_TITLES[indicatorKey] ?? indicatorKey;

  return (
    <li className="bg-slate-900/40">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={`indicator-${indicatorKey}-body`}
        disabled={!expandable}
        onClick={() => setOpen((prev) => !prev)}
        className="flex w-full cursor-pointer flex-wrap items-center gap-2 px-3 py-2 text-left text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400 disabled:cursor-default"
      >
        <span className="min-w-[120px] text-slate-300">{title}</span>
        <SignalBadge
          tone={result.signal}
          ariaLabel={`${title}：${result.short_label}`}
        />
        <span className="flex-1 text-slate-400">{result.short_label}</span>
        {expandable && (
          <span aria-hidden="true" className="text-xs text-slate-500">
            {open ? '收合' : '詳細'}
          </span>
        )}
      </button>
      {open && (
        <div
          id={`indicator-${indicatorKey}-body`}
          className="border-t border-slate-800 bg-slate-950/40"
        >
          {seriesName && (
            <IndicatorChartSection
              symbol={symbol}
              indicatorKey={indicatorKey}
              seriesName={seriesName}
              enabled={open}
            />
          )}
          {hasDetail && (
            <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 px-3 py-2 text-xs text-slate-300">
              {Object.entries(result.detail).map(([k, v]) => (
                <div key={k} className="contents">
                  <dt className="font-mono text-slate-500">
                    {k.replace(/_/g, ' ')}
                  </dt>
                  <dd className="font-mono text-slate-200">{formatDetail(v)}</dd>
                </div>
              ))}
            </dl>
          )}
        </div>
      )}
    </li>
  );
}

interface IndicatorChartSectionProps {
  symbol: string;
  indicatorKey: string;
  seriesName: IndicatorSeriesName;
  enabled: boolean;
}

function IndicatorChartSection({
  symbol,
  indicatorKey,
  seriesName,
  enabled,
}: IndicatorChartSectionProps): JSX.Element {
  const query = useIndicatorSeries(symbol, seriesName, { enabled });
  const title = INDICATOR_TITLES[indicatorKey] ?? indicatorKey;

  return (
    <div className="flex flex-col gap-2 px-3 py-3">
      {query.isLoading && (
        <div className="flex items-center gap-2 text-xs text-slate-400">
          <LoadingSpinner label="載入中…" />
        </div>
      )}
      {query.isError && (
        <p role="alert" className="text-xs text-signal-red">
          走勢資料載入失敗
        </p>
      )}
      {query.data && (
        <>
          <p className="text-sm text-slate-200">{query.data.summary_zh}</p>
          <IndicatorChart
            data={query.data}
            ariaLabel={`${title} 60 日走勢圖`}
          />
        </>
      )}
    </div>
  );
}

interface IndicatorChartProps {
  data: IndicatorSeriesResponse;
  ariaLabel: string;
}

function IndicatorChart({ data, ariaLabel }: IndicatorChartProps): JSX.Element {
  switch (data.indicator) {
    case 'price_vs_ma':
      return (
        <IndicatorMultiLine
          series={data.series}
          lines={PRICE_VS_MA_LINES}
          ariaLabel={ariaLabel}
        />
      );
    case 'rsi':
      return (
        <IndicatorBoundedLine
          series={data.series}
          lines={RSI_LINES}
          thresholds={RSI_THRESHOLDS}
          yAxisMin={0}
          yAxisMax={100}
          ariaLabel={ariaLabel}
        />
      );
    case 'macd':
      return (
        <IndicatorMultiLine
          series={data.series}
          lines={MACD_LINES}
          histogram={MACD_HISTOGRAM}
          ariaLabel={ariaLabel}
        />
      );
    case 'bollinger':
      return (
        <IndicatorMultiLine
          series={data.series}
          lines={BB_LINES}
          shadedBand={BB_SHADED_BAND}
          ariaLabel={ariaLabel}
        />
      );
    case 'volume_anomaly':
      return (
        <IndicatorVolumeBars
          series={data.series}
          upColor="#22c55e"
          downColor="#ef4444"
          flatColor="#475569"
          averageLineColor="#facc15"
          ariaLabel={ariaLabel}
        />
      );
    case 'relative_strength': {
      // Backend returns cumulative returns as decimals (0.04 = +4%); the
      // chart renders raw numbers, so scale to percent here for legibility.
      const series: ReadonlyArray<MultiLineSeriesRow> = data.series.map(
        (row) => ({
          date: row.date,
          ticker_pct: row.ticker_cum_return * 100,
          spx_pct: row.spx_cum_return * 100,
        }),
      );
      return (
        <IndicatorMultiLine
          series={series}
          lines={RELATIVE_STRENGTH_LINES}
          ariaLabel={ariaLabel}
        />
      );
    }
  }
}

function formatDetail(value: unknown): string {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'boolean') return value ? '是' : '否';
  if (typeof value === 'number') {
    if (Number.isInteger(value)) return String(value);
    return Number.parseFloat(value.toFixed(4)).toString();
  }
  if (typeof value === 'string') return value;
  return JSON.stringify(value);
}

function DirectionCard({
  symbol,
  indicators,
  isLoading,
  error,
}: IndicatorsCardProps): JSX.Element {
  const pendingIndicators =
    error instanceof EisweinApiError && error.status === 404;
  return (
    <section
      aria-labelledby="direction-heading"
      className="flex flex-col gap-2 rounded-lg border border-slate-800 bg-slate-900/60 p-4"
    >
      <header>
        <h2 id="direction-heading" className="text-lg font-semibold">
          方向指標（4 項）
        </h2>
      </header>
      {isLoading && <LoadingSpinner label="讀取指標…" />}
      {pendingIndicators && (
        <p role="status" className="text-sm text-slate-400">
          尚無指標資料，請待下一次每日運算。
        </p>
      )}
      {!isLoading && !pendingIndicators && !indicators && error && (
        <p role="alert" className="text-sm text-signal-red">
          載入指標失敗。
        </p>
      )}
      {indicators && (
        <IndicatorList
          symbol={symbol}
          indicators={indicators}
          keys={DIRECTION_INDICATORS}
          emptyMessage="尚無方向指標資料。"
        />
      )}
    </section>
  );
}

function TimingCard({
  symbol,
  indicators,
  isLoading,
}: Omit<IndicatorsCardProps, 'error'>): JSX.Element {
  return (
    <section
      aria-labelledby="timing-heading"
      className="flex flex-col gap-2 rounded-lg border border-slate-800 bg-slate-900/60 p-4"
    >
      <header>
        <h2 id="timing-heading" className="text-lg font-semibold">
          時機指標（2 項）
        </h2>
      </header>
      {isLoading && <LoadingSpinner label="讀取指標…" />}
      {indicators && (
        <IndicatorList
          symbol={symbol}
          indicators={indicators}
          keys={TIMING_INDICATORS}
          emptyMessage="尚無時機指標資料。"
        />
      )}
    </section>
  );
}

interface EntryTiersCardProps {
  signal: TickerSignalResponse | null;
  latestClose: number | null;
}

function EntryTiersCard({ signal, latestClose }: EntryTiersCardProps): JSX.Element {
  const tiers = signal?.entry_tiers ?? null;
  const [a, b, c] = tiers?.split_suggestion ?? [30, 40, 30];
  return (
    <section
      aria-labelledby="entry-heading"
      className="flex flex-col gap-3 rounded-lg border border-slate-800 bg-slate-900/60 p-4"
    >
      <header className="flex items-baseline justify-between">
        <h2 id="entry-heading" className="text-lg font-semibold">
          進場參考價位
        </h2>
        <span className="text-xs text-slate-500">僅供參考（{a}/{b}/{c}）</span>
      </header>
      {!signal && (
        <p role="status" className="text-sm text-slate-400">
          尚無進場參考。待下一次運算。
        </p>
      )}
      {signal && tiers && (
        <div className="flex flex-col gap-4">
          <PriceBar
            label="積極進場（50MA）"
            currentPrice={latestClose}
            targetPrice={parseDecimalString(tiers.aggressive)}
            toneAboveTarget="neutral"
            toneBelowTarget="green"
          />
          <PriceBar
            label="理想進場（20MA / BB 中軌）"
            currentPrice={latestClose}
            targetPrice={parseDecimalString(tiers.ideal)}
            toneAboveTarget="neutral"
            toneBelowTarget="green"
          />
          <PriceBar
            label="保守進場（200MA）"
            currentPrice={latestClose}
            targetPrice={parseDecimalString(tiers.conservative)}
            toneAboveTarget="neutral"
            toneBelowTarget="green"
          />
        </div>
      )}
    </section>
  );
}

interface StopLossCardProps {
  signal: TickerSignalResponse | null;
  latestClose: number | null;
}

function StopLossCard({ signal, latestClose }: StopLossCardProps): JSX.Element {
  const stopLoss = parseDecimalString(signal?.stop_loss ?? null);
  const triggered =
    stopLoss !== null && latestClose !== null && latestClose <= stopLoss;
  return (
    <section
      aria-labelledby="stop-loss-heading"
      className="flex flex-col gap-3 rounded-lg border border-slate-800 bg-slate-900/60 p-4"
    >
      <header>
        <h2 id="stop-loss-heading" className="text-lg font-semibold">
          停損參考
        </h2>
      </header>
      {triggered && (
        <div
          role="alert"
          className="rounded-md border border-signal-red/40 bg-signal-red/10 px-3 py-2 text-sm text-signal-red"
        >
          ⚠️ 現價已跌破停損參考，請檢視持倉。
        </div>
      )}
      {!signal?.stop_loss && !signal && (
        <p role="status" className="text-sm text-slate-400">
          尚無停損參考。
        </p>
      )}
      {signal && (
        <PriceBar
          label="停損參考"
          currentPrice={latestClose}
          targetPrice={stopLoss}
          toneAboveTarget="green"
          toneBelowTarget="red"
        />
      )}
    </section>
  );
}

interface ProsConsCardProps {
  signal: TickerSignalResponse | null;
  isLoading: boolean;
}

function ProsConsCard({ signal, isLoading }: ProsConsCardProps): JSX.Element {
  return (
    <section
      aria-labelledby="pros-cons-heading"
      className="flex flex-col gap-3 rounded-lg border border-slate-800 bg-slate-900/60 p-4"
    >
      <header>
        <h2 id="pros-cons-heading" className="text-lg font-semibold">
          Pros / Cons 總表
        </h2>
      </header>
      {isLoading && <LoadingSpinner label="讀取 Pros/Cons…" />}
      {signal && <ProsConsList items={signal.pros_cons} />}
      {!isLoading && !signal && (
        <p role="status" className="text-sm text-slate-400">
          尚無 Pros/Cons 資料。
        </p>
      )}
    </section>
  );
}
