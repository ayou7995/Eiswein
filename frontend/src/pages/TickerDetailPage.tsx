import { useState } from 'react';
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
import { Tooltip } from '../components/Tooltip';
import {
  MaPositionEnhancedDetail,
  MaPositionHeadlineExplainable,
} from '../components/MaPositionEnhancedDetail';
import {
  RsiEnhancedDetail,
  RsiHeadlineExplainable,
} from '../components/RsiEnhancedDetail';
import {
  VolumeAnomalyEnhancedDetail,
  VolumeAnomalyHeadlineExplainable,
} from '../components/VolumeAnomalyEnhancedDetail';
import {
  RelativeStrengthEnhancedDetail,
  RelativeStrengthHeadlineExplainable,
} from '../components/RelativeStrengthEnhancedDetail';
import { useTickerSignal } from '../hooks/useTickerSignal';
import { useTickerIndicators } from '../hooks/useTickerIndicators';
import { useTickerPrices } from '../hooks/useTickerPrices';
import { useIndicatorSeries } from '../hooks/useIndicatorSeries';
import { IndicatorRangeSelector } from '../components/IndicatorRangeSelector';
import {
  MARKET_INDICATOR_RANGES,
  type MarketIndicatorRangeKey,
} from '../api/marketIndicatorSeries';
import type { TickerSignalResponse } from '../api/tickerSignal';
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

      <RoadmapNote />
    </div>
  );
}

// v2 backlog surfaced inline so the user (and reviewers) can see what
// was deliberately deferred. Keep terse — this isn't a release-notes
// dump, just a forward-looking marker.
function RoadmapNote(): JSX.Element {
  return (
    <section
      aria-labelledby="ticker-roadmap-heading"
      className="flex flex-col gap-1 rounded-lg border border-dashed border-slate-700 bg-slate-900/40 p-4 text-xs text-slate-400"
    >
      <h2 id="ticker-roadmap-heading" className="text-sm font-semibold text-slate-300">
        TODO（v2 規劃）
      </h2>
      <ul className="ml-4 list-disc space-y-1">
        <li>
          <span className="text-slate-300">資金流向（OBV / VPT）</span>
          ：目前「成交量異常」只看今日 spike，無法捕捉日常微小資金流。等
          v2 forward-test 累積 6 個月資料後，評估是否加入 OBV（On-Balance
          Volume）作為趨勢補充——每日累計、可看與股價的背離，比稀疏的
          spike 計數更穩。
        </li>
      </ul>
    </section>
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
            {signal.stop_loss && (
              <span data-testid="stop-loss-pill">
                停損參考：
                <Tooltip text="200MA × 0.97">
                  <span className="cursor-help underline decoration-dotted decoration-slate-600 underline-offset-2">
                    ${signal.stop_loss}
                  </span>
                </Tooltip>
              </span>
            )}
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

const PRICE_VS_MA_HEADLINE_LABELS = {
  ruleTitle: '價格 vs 50/200MA 規則',
  ruleNote:
    '此燈號是個股方向 4 項中的「位階」項；展開列可看距離尺標、近期黃金/死亡交叉、與看點。',
};

const RSI_HEADLINE_LABELS = {
  ruleTitle: 'RSI 紅黃綠燈規則',
  ruleNote:
    '⚠️ 鈍化現象：強勢趨勢中 RSI 可能連續數週停在 >70 或 <30，「碰到 70 就賣 / 碰到 30 就買」會錯過大行情或接刀。必須配合週線確認 + 價格動作判讀真正反轉。RSI 屬個股方向 4 項中的「動能」項，是 contrarian indicator — 超買偏空、超賣偏多。',
};

const VOLUME_ANOMALY_HEADLINE_LABELS = {
  ruleTitle: '成交量異常紅黃綠燈規則',
  ruleNote:
    '此燈號是個股方向 4 項中的「資金動能」項。同 O\'Neil A/D Day 邏輯 — 機構動倉一定要量。spike 閾值 2× 是經驗值，可視個股流動性微調。',
};

const RELATIVE_STRENGTH_HEADLINE_LABELS = {
  ruleTitle: '相對強度紅黃綠燈規則',
  ruleNote:
    '此燈號是個股方向 4 項中的「對比大盤」項。20 日是 O\'Neil 系統的標準窗口（≈1 個交易月）。連續多週「強於大盤」常見於領漲類股，是中期持有的好訊號；連續「弱於大盤」是換股的警訊。',
};

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
  const isPriceVsMa = indicatorKey === 'price_vs_ma';
  const isRsi = indicatorKey === 'rsi';
  const isVolumeAnomaly = indicatorKey === 'volume_anomaly';
  const isRelativeStrength = indicatorKey === 'relative_strength';

  // Non-expandable rows (insufficient data, no chart, no detail) keep
  // the simple flat row — no <details> needed.
  if (!expandable) {
    return (
      <li className="bg-slate-900/40">
        <div className="flex flex-wrap items-center gap-2 px-3 py-2 text-sm">
          <span className="min-w-[120px] text-slate-300">{title}</span>
          <SignalBadge
            tone={result.signal}
            ariaLabel={`${title}：${result.short_label}`}
          />
          <span className="flex-1 text-slate-400">{result.short_label}</span>
        </div>
      </li>
    );
  }

  return (
    <li className="bg-slate-900/40">
      <details
        onToggle={(event) =>
          setOpen((event.currentTarget as HTMLDetailsElement).open)
        }
      >
        <summary
          data-testid={`indicator-row-${indicatorKey}-summary`}
          className="flex cursor-pointer flex-wrap items-center gap-2 px-3 py-2 text-sm text-slate-200 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
        >
          <span className="min-w-[120px] text-slate-300">{title}</span>
          <SignalBadge
            tone={result.signal}
            ariaLabel={`${title}：${result.short_label}`}
          />
          <span className="flex-1 text-slate-400">
            {isPriceVsMa ? (
              <MaPositionHeadlineExplainable
                shortLabel={result.short_label}
                detail={result.detail}
                labels={PRICE_VS_MA_HEADLINE_LABELS}
              />
            ) : isRsi ? (
              <RsiHeadlineExplainable
                shortLabel={result.short_label}
                detail={result.detail}
                labels={RSI_HEADLINE_LABELS}
              />
            ) : isVolumeAnomaly ? (
              <VolumeAnomalyHeadlineExplainable
                shortLabel={result.short_label}
                detail={result.detail}
                labels={VOLUME_ANOMALY_HEADLINE_LABELS}
              />
            ) : isRelativeStrength ? (
              <RelativeStrengthHeadlineExplainable
                shortLabel={result.short_label}
                detail={result.detail}
                labels={RELATIVE_STRENGTH_HEADLINE_LABELS}
              />
            ) : (
              result.short_label
            )}
          </span>
          <span aria-hidden="true" className="text-xs text-slate-500">
            {open ? '收合' : '詳細'}
          </span>
        </summary>
        <div className="border-t border-slate-800 bg-slate-950/40">
          {seriesName && (
            <IndicatorChartSection
              symbol={symbol}
              indicatorKey={indicatorKey}
              seriesName={seriesName}
              enabled={open}
            />
          )}
          {isPriceVsMa ? (
            <MaPositionEnhancedDetail detail={result.detail} />
          ) : isRsi ? (
            <RsiEnhancedDetail detail={result.detail} />
          ) : isVolumeAnomaly ? (
            <VolumeAnomalyEnhancedDetail detail={result.detail} />
          ) : isRelativeStrength ? (
            <RelativeStrengthEnhancedDetail detail={result.detail} />
          ) : (
            hasDetail && (
              <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 px-3 py-2 text-xs text-slate-300">
                {Object.entries(result.detail).map(([k, v]) => (
                  <div key={k} className="contents">
                    <dt className="font-mono text-slate-500">
                      {k.replace(/_/g, ' ')}
                    </dt>
                    <dd className="font-mono text-slate-200">
                      {formatDetail(v)}
                    </dd>
                  </div>
                ))}
              </dl>
            )
          )}
        </div>
      </details>
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
  // Per-chart range state — same UX as the market regime cards. Default
  // to 3M (60 trading days) which matches every per-ticker indicator's
  // legacy window.
  const [range, setRange] = useState<MarketIndicatorRangeKey>('3M');
  const query = useIndicatorSeries(symbol, seriesName, {
    enabled,
    days: rangeToDays(range),
  });
  const title = INDICATOR_TITLES[indicatorKey] ?? indicatorKey;

  return (
    <div className="flex flex-col gap-2 px-3 py-3">
      <header className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-slate-200">{query.data?.summary_zh ?? ''}</p>
        <IndicatorRangeSelector
          value={range}
          onChange={setRange}
          indicatorLabel={`${title} 區間`}
        />
      </header>
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
        <IndicatorChart data={query.data} ariaLabel={`${title} 走勢圖`} />
      )}
    </div>
  );
}

function rangeToDays(range: MarketIndicatorRangeKey): number {
  return MARKET_INDICATOR_RANGES.find((r) => r.key === range)?.days ?? 60;
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
