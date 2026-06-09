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
import { ActionBadgePair } from '../components/ActionBadgePair';
import { NextCatalystChip } from '../components/NextCatalystChip';
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
import {
  MacdEnhancedDetail,
  MacdHeadlineExplainable,
} from '../components/MacdEnhancedDetail';
import {
  BollingerEnhancedDetail,
  BollingerHeadlineExplainable,
} from '../components/BollingerEnhancedDetail';
import {
  AdxEnhancedDetail,
  AdxHeadlineExplainable,
} from '../components/AdxEnhancedDetail';
import {
  AtrEnhancedDetail,
  AtrHeadlineExplainable,
} from '../components/AtrEnhancedDetail';
import {
  TtmSqueezeEnhancedDetail,
  TtmSqueezeHeadlineExplainable,
} from '../components/TtmSqueezeEnhancedDetail';
import {
  ChoEnhancedDetail,
  ChoHeadlineExplainable,
} from '../components/ChoEnhancedDetail';
import { DxyEnhancedDetail } from '../components/DxyEnhancedDetail';
import { FedRateEnhancedDetail } from '../components/FedRateEnhancedDetail';
import { useTickerSignal } from '../hooks/useTickerSignal';
import { useTickerIndicators } from '../hooks/useTickerIndicators';
import { useTickerPrices } from '../hooks/useTickerPrices';
import { useIndicatorSeries } from '../hooks/useIndicatorSeries';
import { useMarketIndicatorSeries } from '../hooks/useMarketIndicatorSeries';
import { IndicatorRangeSelector } from '../components/IndicatorRangeSelector';
import { TimeframeChip } from '../components/TimeframeChip';
import { INDICATOR_TIMEFRAMES } from '../lib/timeframes';
import { computeYBounds } from '../lib/yAxisAutoFit';
import { DataFreshnessBadge } from '../components/DataFreshnessBadge';
import { IndicatorIndexBar } from '../components/IndicatorIndexBar';
import { RelatedIndicatorsRow } from '../components/RelatedIndicatorsRow';
import { StalenessPill } from '../components/StalenessPill';
import { useSystemInfo } from '../hooks/useSettings';
import { SignalAccuracySection } from '../components/SignalAccuracySection';
import {
  MARKET_INDICATOR_RANGES,
  type MarketIndicatorRangeKey,
  type MarketIndicatorSeriesName,
} from '../api/marketIndicatorSeries';
import type { TickerSignalResponse } from '../api/tickerSignal';
import type { IndicatorResult } from '../api/tickerIndicators';
import type { PriceRange } from '../api/tickerPrices';
import type {
  IndicatorSeriesName,
  IndicatorSeriesResponse,
} from '../api/tickerIndicatorSeries';
import { EisweinApiError } from '../api/errors';

// Per-ticker indicators grouped by HORIZON, not by semantic category. The
// v1 split ("方向 / 時機 / 總經") mixed short + mid timeframes in each
// section, which made it hard for the operator to answer "what does this
// indicator say about the next 3 days vs the next 3 weeks?". v2 Phase 1
// (2026-06) flipped to a strict short / mid / long layout so the
// timeframe is obvious at a glance — backend INDICATOR_TIMEFRAMES is the
// source of truth for which indicator goes into which bucket.
//
// All indicators are rendered inline (no <details> wrapper) — the
// operator scrolls top-to-bottom through every data view in one pass.
const SHORT_TERM_INDICATORS = [
  'rsi',
  'volume_anomaly',
  'macd',
  'bollinger',
  // v2 Phase 2: ATR is the volatility scale that drives the
  // ATR-based stop-loss. Sits in short because it answers "is today's
  // move unusual vs the last 14 bars?".
  'atr',
  // v2 Phase 3: TTM Squeeze fires breakout direction over 3-5 days.
  'ttm_squeeze',
];
const MID_TERM_INDICATORS = [
  'price_vs_ma',
  'relative_strength',
  // v2 Phase 2: ADX is an INDEPENDENT mid-term trend-strength gauge —
  // read alongside the other mid indicators, NOT a modifier on them.
  'adx',
  // v2 Phase 3: CHO is the Sherry "big players accumulating" gauge.
  'cho',
];
const LONG_TERM_INDICATORS = ['dxy', 'fed_rate'];

const INDICATOR_TITLES: Record<string, string> = {
  price_vs_ma: '價格 vs 50/200 MA',
  rsi: 'RSI',
  volume_anomaly: '成交量異常',
  relative_strength: '相對強度',
  macd: 'MACD',
  bollinger: 'Bollinger Bands',
  // v2 Phase 2 — ADX reads trend strength as an independent gauge; ATR
  // is the per-stock volatility scale that also feeds the stop-loss
  // distance.
  adx: 'ADX (趨勢強度)',
  atr: 'ATR (波動率)',
  // v2 Phase 3 — TTM Squeeze + CHO.
  ttm_squeeze: 'TTM Squeeze (壓縮點火)',
  cho: 'Chaikin (大戶吃貨)',
  dxy: 'DXY (美元指數)',
  fed_rate: 'Fed 利率',
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
  adx: 'adx',
  atr: 'atr',
  ttm_squeeze: 'ttm_squeeze',
  cho: 'cho',
};

// Macro indicators come from the market-indicator series endpoints (shared
// across tickers) — different namespace from the per-ticker series.
const MACRO_SERIES_NAME: Record<string, MarketIndicatorSeriesName> = {
  dxy: 'dxy',
  fed_rate: 'fed_rate',
};

const PRICE_VS_MA_LINES: ReadonlyArray<MultiLineDefinition> = [
  { key: 'price', label: '收盤價', color: '#1c1917', width: 2 },
  { key: 'ma50', label: '50 MA', color: '#0284c7', style: 'dashed', width: 2 },
  { key: 'ma200', label: '200 MA', color: '#d97706', style: 'dashed', width: 1 },
];

const RSI_LINES: ReadonlyArray<BoundedLineDefinition> = [
  { key: 'daily', label: '日 RSI', color: '#0284c7' },
  { key: 'weekly', label: '週 RSI', color: '#8b5cf6' },
];

const RSI_THRESHOLDS: ReadonlyArray<BoundedLineThreshold> = [
  { value: 30, label: '超賣', color: '#059669', fillBetween: 'below' },
  { value: 70, label: '超買', color: '#e11d48', fillBetween: 'above' },
];

const MACD_LINES: ReadonlyArray<MultiLineDefinition> = [
  { key: 'macd', label: 'MACD', color: '#0284c7', width: 2 },
  { key: 'signal', label: 'Signal', color: '#d97706', width: 1 },
];

const MACD_HISTOGRAM: MultiLineHistogram = {
  key: 'histogram',
  positiveColor: '#059669',
  negativeColor: '#e11d48',
};

const BB_LINES: ReadonlyArray<MultiLineDefinition> = [
  { key: 'price', label: '收盤價', color: '#1c1917', width: 2 },
  { key: 'middle', label: '中軌（20MA）', color: '#8b5cf6', style: 'dashed', width: 1 },
];

const BB_SHADED_BAND: MultiLineShadedBand = {
  upperKey: 'upper',
  lowerKey: 'lower',
  opacity: 0.18,
  color: '#0284c7',
};

const RELATIVE_STRENGTH_LINES: ReadonlyArray<MultiLineDefinition> = [
  { key: 'ticker_pct', label: '個股累積報酬 (%)', color: '#0284c7', width: 2 },
  {
    key: 'spx_pct',
    label: 'SPX 累積報酬 (%)',
    color: '#78716c',
    style: 'dashed',
    width: 1,
  },
];

const ADX_LINES: ReadonlyArray<BoundedLineDefinition> = [
  { key: 'adx', label: 'ADX', color: '#1c1917' },
  { key: 'plus_di', label: '+DI', color: '#059669' },
  { key: 'minus_di', label: '-DI', color: '#e11d48' },
];

const ADX_THRESHOLDS: ReadonlyArray<BoundedLineThreshold> = [
  { value: 20, label: '盤整 (<20)', color: '#a8a29e', fillBetween: 'below' },
  { value: 25, label: '強趨勢 (≥25)', color: '#059669', fillBetween: 'above' },
];

const ATR_LINES: ReadonlyArray<BoundedLineDefinition> = [
  { key: 'atr_pct', label: 'ATR %', color: '#1c1917' },
];

const ATR_THRESHOLDS: ReadonlyArray<BoundedLineThreshold> = [
  { value: 1.5, label: '平靜 (<1.5%)', color: '#059669', fillBetween: 'below' },
  { value: 3.5, label: '偏高 (≥3.5%)', color: '#e11d48', fillBetween: 'above' },
];

const TTM_MOMENTUM_LINES: ReadonlyArray<MultiLineDefinition> = [
  { key: 'momentum', label: '動能 % of close', color: '#0284c7', width: 2 },
];

const TTM_MOMENTUM_HISTOGRAM: MultiLineHistogram = {
  key: 'momentum',
  positiveColor: '#059669',
  negativeColor: '#e11d48',
};

const CHO_LINES: ReadonlyArray<MultiLineDefinition> = [
  { key: 'cho', label: 'CHO', color: '#1c1917', width: 2 },
];

function formatMagnitude(value: number): string {
  const abs = Math.abs(value);
  const sign = value < 0 ? '−' : '';
  if (abs >= 1e9) return `${sign}${(abs / 1e9).toFixed(1)}B`;
  if (abs >= 1e6) return `${sign}${(abs / 1e6).toFixed(1)}M`;
  if (abs >= 1e3) return `${sign}${(abs / 1e3).toFixed(1)}k`;
  return `${sign}${abs.toFixed(2)}`;
}

function formatPercent(value: number): string {
  return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`;
}

export function TickerDetailPage(): JSX.Element {
  const { symbol: rawSymbol } = useParams<{ symbol: string }>();
  const symbol = rawSymbol?.toUpperCase() ?? '';
  const [range, setRange] = useState<PriceRange>('6M');

  const signalQuery = useTickerSignal(symbol);
  const indicatorsQuery = useTickerIndicators(symbol);
  const pricesQuery = useTickerPrices(symbol, range);
  const sysInfoQuery = useSystemInfo();

  const signal = signalQuery.data;
  const signalError = signalQuery.error;

  if (!symbol) {
    return (
      <section aria-labelledby="ticker-heading">
        <h1 id="ticker-heading" className="text-2xl font-semibold">
          標的分析
        </h1>
        <p className="mt-2 text-sm text-rose-600">缺少股票代碼。</p>
      </section>
    );
  }

  const indicators = indicatorsQuery.data?.indicators ?? null;
  const indicatorsError =
    indicatorsQuery.error instanceof Error ? indicatorsQuery.error : null;
  const pendingIndicators =
    indicatorsError instanceof EisweinApiError &&
    indicatorsError.status === 404;

  return (
    <div className="flex flex-col gap-6">
      <TickerHeader
        symbol={symbol}
        signal={signal ?? null}
        signalError={signalError instanceof Error ? signalError : null}
        signalLoading={signalQuery.isLoading}
        freshness={sysInfoQuery.data?.data_freshness ?? null}
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

      {signal && signal.pros_cons.length > 0 && (
        <IndicatorIndexBar
          items={signal.pros_cons}
          titleFor={(name) => INDICATOR_TITLES[name] ?? name}
        />
      )}

      <IndicatorGroup
        title="短期 (3-5 天)"
        subtitle="RSI · 量能 · MACD · Bollinger — 戰術進出場依據"
        keys={SHORT_TERM_INDICATORS}
        symbol={symbol}
        indicators={indicators}
        prosConsItems={signal?.pros_cons ?? []}
        snapshotDate={indicatorsQuery.data?.date ?? null}
        isLoading={indicatorsQuery.isLoading}
        pending={pendingIndicators}
        error={!pendingIndicators ? indicatorsError : null}
      />

      <IndicatorGroup
        title="中期 (2-4 週)"
        subtitle="價格 vs 均線 · 相對強度 — 持倉判斷依據"
        keys={MID_TERM_INDICATORS}
        symbol={symbol}
        indicators={indicators}
        prosConsItems={signal?.pros_cons ?? []}
        snapshotDate={indicatorsQuery.data?.date ?? null}
        isLoading={indicatorsQuery.isLoading}
        pending={pendingIndicators}
        error={null}
      />

      <IndicatorGroup
        title="長期 / 總經背景"
        subtitle="DXY · Fed 利率 — 部位配置背景"
        keys={LONG_TERM_INDICATORS}
        symbol={symbol}
        indicators={indicators}
        prosConsItems={signal?.pros_cons ?? []}
        snapshotDate={indicatorsQuery.data?.date ?? null}
        isLoading={indicatorsQuery.isLoading}
        pending={pendingIndicators}
        error={null}
      />

      <SignalAccuracySection symbol={symbol} />
    </div>
  );
}

interface TickerHeaderProps {
  symbol: string;
  signal: TickerSignalResponse | null;
  signalError: Error | null;
  signalLoading: boolean;
  freshness: import('../api/settings').DataFreshness | null;
}

function TickerHeader({
  symbol,
  signal,
  signalError,
  signalLoading,
  freshness,
}: TickerHeaderProps): JSX.Element {
  const pendingSignal =
    signalError instanceof EisweinApiError && signalError.status === 404;
  return (
    <section
      aria-labelledby="ticker-heading"
      // Sticky so the operator always knows which symbol they're on as
      // they scroll through the ~5000-6000px of indicator detail below.
      className="sticky top-0 z-10 -mx-4 flex flex-col gap-2 border-b border-stone-200 bg-stone-50/85 px-4 py-3 backdrop-blur sm:-mx-6 sm:px-6 lg:-mx-8 lg:px-8"
    >
      {/* Row 1 — primary: symbol + dual action badges + stats grid */}
      <header className="flex flex-wrap items-start justify-between gap-x-6 gap-y-2">
        <div className="flex flex-wrap items-center gap-3">
          <h1 id="ticker-heading" className="font-mono text-2xl font-semibold">
            {symbol}
          </h1>
          {signalLoading && <LoadingSpinner label="讀取訊號…" />}
          {signal && (
            <ActionBadgePair
              midAction={signal.action}
              midGreen={signal.direction_green_count}
              midRed={signal.direction_red_count}
              midTimingBadge={signal.timing_badge}
              shortAction={signal.action_short}
              shortGreen={signal.direction_short_green_count}
              shortRed={signal.direction_short_red_count}
            />
          )}
          {pendingSignal && (
            <span className="text-xs text-stone-500">分析運算中</span>
          )}
        </div>
        {signal && (
          <dl className="grid grid-cols-[auto_auto] gap-x-3 gap-y-0.5 text-xs">
            {signal.stop_loss && (
              <>
                <dt className="text-stone-400">停損參考</dt>
                <dd
                  data-testid="stop-loss-pill"
                  className="text-right font-mono text-stone-700"
                >
                  <Tooltip text="200MA × 0.97">
                    <span className="cursor-help underline decoration-dotted decoration-stone-400 underline-offset-2">
                      ${signal.stop_loss}
                    </span>
                  </Tooltip>
                </dd>
              </>
            )}
            <dt className="text-stone-400">最近交易日</dt>
            <dd className="text-right font-mono text-stone-700">{signal.date}</dd>
            <dt className="text-stone-400">市場態勢</dt>
            <dd className="text-right text-stone-700">
              {POSTURE_LABELS[signal.market_posture_at_compute] ??
                signal.market_posture_at_compute}
            </dd>
            <dt className="text-stone-400">指標版本</dt>
            <dd className="text-right font-mono text-stone-500">
              {signal.indicator_version}
            </dd>
          </dl>
        )}
      </header>
      {/* Row 2 — sub-row: catalyst + freshness chips */}
      {(signal || freshness) && (
        <div className="flex flex-wrap items-center gap-2">
          <NextCatalystChip symbol={symbol} />
          {freshness && <DataFreshnessBadge freshness={freshness} />}
        </div>
      )}
    </section>
  );
}

interface IndicatorGroupProps {
  title: string;
  subtitle: string;
  keys: readonly string[];
  symbol: string;
  indicators: Record<string, IndicatorResult> | null;
  prosConsItems: readonly import('../api/prosCons').ProsConsItem[];
  snapshotDate: string | null;
  isLoading: boolean;
  pending: boolean;
  error: Error | null;
}

function IndicatorGroup({
  title,
  subtitle,
  keys,
  symbol,
  indicators,
  prosConsItems,
  snapshotDate,
  isLoading,
  pending,
  error,
}: IndicatorGroupProps): JSX.Element {
  return (
    <section
      aria-label={`${title}（${subtitle}）`}
      className="flex flex-col gap-3"
    >
      <header className="flex items-baseline gap-2">
        <h2 className="text-lg font-semibold text-stone-900">{title}</h2>
        <span className="text-xs text-stone-500">{subtitle}</span>
      </header>
      {isLoading && (
        <div className="rounded-2xl border border-stone-200 bg-white p-6">
          <LoadingSpinner label="讀取指標…" />
        </div>
      )}
      {pending && (
        <div className="rounded-2xl border border-stone-200 bg-white p-6">
          <p role="status" className="text-sm text-stone-500">
            尚無指標資料，請待下一次每日運算。
          </p>
        </div>
      )}
      {error && !pending && (
        <div className="rounded-2xl border border-rose-300 bg-rose-50 p-6">
          <p role="alert" className="text-sm text-rose-700">
            載入指標失敗。
          </p>
        </div>
      )}
      {indicators && (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {keys.map((key) => {
            const result = indicators[key];
            if (!result) return null;
            return (
              <IndicatorCard
                key={key}
                symbol={symbol}
                indicatorKey={key}
                result={result}
                prosConsItems={prosConsItems}
                snapshotDate={snapshotDate}
              />
            );
          })}
        </div>
      )}
    </section>
  );
}

const PRICE_VS_MA_HEADLINE_LABELS = {
  ruleTitle: '價格 vs 50/200MA 規則',
  ruleNote:
    '此燈號是「中期方向」5 票之 1 的「位階」項(中期 5 vote = price_vs_ma + rsi + volume_anomaly + relative_strength + cho)。只投中期,不投短期。下方包含距離尺標、近期黃金/死亡交叉、與看點。',
};

const RSI_HEADLINE_LABELS = {
  ruleTitle: 'RSI 紅黃綠燈規則',
  ruleNote:
    '⚠️ 鈍化現象:強勢趨勢中 RSI 可能連續數週停在 >70 或 <30,「碰到 70 就賣 / 碰到 30 就買」會錯過大行情或接刀。必須配合週線確認 + 價格動作判讀真正反轉。RSI 是 dual-vote 成員 — 同時投中期 5 票 + 短期 5 票(短期 5 vote = rsi + macd + bollinger + volume_anomaly + ttm_squeeze)。Contrarian indicator — 超買偏空、超賣偏多。',
};

const VOLUME_ANOMALY_HEADLINE_LABELS = {
  ruleTitle: '成交量異常紅黃綠燈規則',
  ruleNote:
    '此燈號是 dual-vote 成員 — 同時投中期 5 票 + 短期 5 票的「資金動能」項。同 O\'Neil A/D Day 邏輯 — 機構動倉一定要量。spike 閾值 2× 是經驗值,可視個股流動性微調。',
};

const RELATIVE_STRENGTH_HEADLINE_LABELS = {
  ruleTitle: '相對強度紅黃綠燈規則',
  ruleNote:
    '此燈號是「中期方向」5 票之 1 的「對比大盤」項。只投中期,不投短期。20 日是 O\'Neil 系統的標準窗口(≈1 個交易月)。連續多週「強於大盤」常見於領漲類股,是中期持有的好訊號;連續「弱於大盤」是換股的警訊。',
};

const MACD_HEADLINE_LABELS = {
  ruleTitle: 'MACD 紅黃綠燈規則',
  ruleNote:
    '此燈號是「短期方向」5 票之 1 的「動能交叉」項。只投短期,不投中期。MACD 屬「事後型」指標 — 交叉發生後才確認,不能預測。但對「現在該停利還是再加碼」這類問題很實用。配合下方走勢圖看 histogram 是否擴張/收縮,比單看當下的數字更可靠。',
};

const BOLLINGER_HEADLINE_LABELS = {
  ruleTitle: '布林通道紅黃綠燈規則',
  ruleNote:
    '此燈號是「短期方向」5 票之 1 的「波動位置」項。只投短期,不投中期。通道是 mean-reversion 工具:價格突破 ±2σ 統計上會回歸,但**強趨勢可以沿著上/下軌走多日**("riding the band")。所以單獨看會誤判,要配合 RSI 和成交量一起判讀。',
};

const ADX_HEADLINE_LABELS = {
  ruleTitle: 'ADX 趨勢強度紅黃綠燈規則',
  ruleNote:
    '此燈號是獨立的「中期趨勢強度」讀數,跟其他指標分開讀。ADX < 25 = 盤整,ADX ≥ 25 = 趨勢明朗。+DI / -DI 之差告訴你趨勢偏多還是偏空(獨立資訊,不投票)。ADX 走弱（slope < -0.5）= 趨勢開始減速,黃燈警示。',
};

const ATR_HEADLINE_LABELS = {
  ruleTitle: 'ATR 波動度紅黃綠燈規則',
  ruleNote:
    '此燈號是「波動度尺規」— 告訴你這支股票現在每日真實震幅是大是小。ATR 不分多空，RED 不是「賣出」，而是「波動偏高，部位要縮、停損要緊」。Eiswein 用 close − 2 × ATR 算停損距離，比固定 % 停損更尊重每支股票自己的個性。',
};

const TTM_SQUEEZE_HEADLINE_LABELS = {
  ruleTitle: 'TTM Squeeze 紅黃綠燈規則',
  ruleNote:
    '此燈號是短期 5-vote 中的「波動率壓縮 → 爆發方向」投票。Carter 的 TTM 系統把波動率視為彈簧 — 壓縮越久，爆發越大。Squeeze 醞釀期黃燈、爆發方向決定綠紅。配合 RSI / MACD 看一致性。',
};

const CHO_HEADLINE_LABELS = {
  ruleTitle: 'Chaikin Oscillator 紅黃綠燈規則',
  ruleNote:
    '此燈號是中期 5-vote 中的「累積/分配加速度」投票。對應 Sherry 的「大戶吃貨綠燈群聚」概念 — CHO 由量加權，難以人為操縱。需要 2-4 週累積後才會出現結構性訊號，所以不能單獨用作短期進出依據。',
};

interface IndicatorCardProps {
  symbol: string;
  indicatorKey: string;
  result: IndicatorResult;
  prosConsItems: readonly import('../api/prosCons').ProsConsItem[];
  snapshotDate: string | null;
}

function IndicatorCard({
  symbol,
  indicatorKey,
  result,
  prosConsItems,
  snapshotDate,
}: IndicatorCardProps): JSX.Element {
  const seriesName = INDICATOR_SERIES_NAME[indicatorKey];
  const macroSeriesName = MACRO_SERIES_NAME[indicatorKey];
  const title = INDICATOR_TITLES[indicatorKey] ?? indicatorKey;
  const isPriceVsMa = indicatorKey === 'price_vs_ma';
  const isRsi = indicatorKey === 'rsi';
  const isVolumeAnomaly = indicatorKey === 'volume_anomaly';
  const isRelativeStrength = indicatorKey === 'relative_strength';
  const isMacd = indicatorKey === 'macd';
  const isBollinger = indicatorKey === 'bollinger';
  const isAdx = indicatorKey === 'adx';
  const isAtr = indicatorKey === 'atr';
  const isTtmSqueeze = indicatorKey === 'ttm_squeeze';
  const isCho = indicatorKey === 'cho';
  const isDxy = indicatorKey === 'dxy';
  const isFedRate = indicatorKey === 'fed_rate';

  return (
    <section
      id={`indicator-${indicatorKey}`}
      data-testid={`indicator-card-${indicatorKey}`}
      className="flex flex-col gap-3 rounded-2xl border border-stone-200 bg-white p-6 scroll-mt-24"
    >
      <header className="flex flex-wrap items-center gap-2">
        <h3 className="text-base font-semibold text-stone-900">{title}</h3>
        <SignalBadge
          tone={result.signal}
          ariaLabel={`${title}：${result.short_label}`}
        />
        <TimeframeChip indicatorName={indicatorKey} />
        {snapshotDate && (
          <StalenessPill
            dataAsOf={result.data_as_of}
            snapshotDate={snapshotDate}
          />
        )}
        <span className="text-sm text-stone-600">
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
          ) : isMacd ? (
            <MacdHeadlineExplainable
              shortLabel={result.short_label}
              detail={result.detail}
              labels={MACD_HEADLINE_LABELS}
            />
          ) : isBollinger ? (
            <BollingerHeadlineExplainable
              shortLabel={result.short_label}
              detail={result.detail}
              labels={BOLLINGER_HEADLINE_LABELS}
            />
          ) : isAdx ? (
            <AdxHeadlineExplainable
              shortLabel={result.short_label}
              detail={result.detail}
              labels={ADX_HEADLINE_LABELS}
            />
          ) : isAtr ? (
            <AtrHeadlineExplainable
              shortLabel={result.short_label}
              detail={result.detail}
              labels={ATR_HEADLINE_LABELS}
            />
          ) : isTtmSqueeze ? (
            <TtmSqueezeHeadlineExplainable
              shortLabel={result.short_label}
              detail={result.detail}
              labels={TTM_SQUEEZE_HEADLINE_LABELS}
            />
          ) : isCho ? (
            <ChoHeadlineExplainable
              shortLabel={result.short_label}
              detail={result.detail}
              labels={CHO_HEADLINE_LABELS}
            />
          ) : (
            result.short_label
          )}
        </span>
      </header>

      {seriesName && (
        <IndicatorChartSection
          symbol={symbol}
          indicatorKey={indicatorKey}
          seriesName={seriesName}
        />
      )}
      {macroSeriesName && (
        <MacroChartSection
          indicatorKey={indicatorKey}
          seriesName={macroSeriesName}
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
      ) : isMacd ? (
        <MacdEnhancedDetail detail={result.detail} />
      ) : isBollinger ? (
        <BollingerEnhancedDetail detail={result.detail} />
      ) : isAdx ? (
        <AdxEnhancedDetail detail={result.detail} />
      ) : isAtr ? (
        <AtrEnhancedDetail detail={result.detail} />
      ) : isTtmSqueeze ? (
        <TtmSqueezeEnhancedDetail detail={result.detail} />
      ) : isCho ? (
        <ChoEnhancedDetail detail={result.detail} />
      ) : isDxy ? (
        <DxyEnhancedDetail detail={result.detail} />
      ) : isFedRate ? (
        <FedRateEnhancedDetail detail={result.detail} />
      ) : (
        Object.keys(result.detail).length > 0 && (
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs text-stone-700">
            {Object.entries(result.detail).map(([k, v]) => (
              <div key={k} className="contents">
                <dt className="font-mono text-stone-400">
                  {k.replace(/_/g, ' ')}
                </dt>
                <dd className="font-mono text-stone-800">{formatDetail(v)}</dd>
              </div>
            ))}
          </dl>
        )
      )}
      <RelatedIndicatorsRow
        currentName={indicatorKey}
        items={prosConsItems}
        titleFor={(name) => INDICATOR_TITLES[name] ?? name}
      />
    </section>
  );
}

interface IndicatorChartSectionProps {
  symbol: string;
  indicatorKey: string;
  seriesName: IndicatorSeriesName;
}

function IndicatorChartSection({
  symbol,
  indicatorKey,
  seriesName,
}: IndicatorChartSectionProps): JSX.Element {
  const [range, setRange] = useState<MarketIndicatorRangeKey>(
    defaultRangeForIndicator(indicatorKey),
  );
  // No `enabled` gate — every indicator card is rendered always-open per
  // Change C, so we fetch as soon as the section mounts.
  const query = useIndicatorSeries(symbol, seriesName, {
    enabled: true,
    days: rangeToParam(range),
  });
  const title = INDICATOR_TITLES[indicatorKey] ?? indicatorKey;

  return (
    <div className="flex flex-col gap-2">
      <header className="flex flex-wrap items-center justify-end gap-2">
        <IndicatorRangeSelector
          value={range}
          onChange={setRange}
          indicatorLabel={`${title} 區間`}
        />
      </header>
      {query.isLoading && (
        <div className="flex items-center gap-2 text-xs text-stone-500">
          <LoadingSpinner label="載入中…" />
        </div>
      )}
      {query.isError && (
        <p role="alert" className="text-xs text-rose-700">
          走勢資料載入失敗
        </p>
      )}
      {query.data && (
        <IndicatorChart data={query.data} ariaLabel={`${title} 走勢圖`} />
      )}
    </div>
  );
}

interface MacroChartSectionProps {
  indicatorKey: string;
  seriesName: MarketIndicatorSeriesName;
}

function MacroChartSection({
  indicatorKey,
  seriesName,
}: MacroChartSectionProps): JSX.Element {
  const [range, setRange] = useState<MarketIndicatorRangeKey>(
    defaultRangeForIndicator(indicatorKey),
  );
  const query = useMarketIndicatorSeries(seriesName, {
    days: rangeToParam(range),
  });
  const title = INDICATOR_TITLES[indicatorKey] ?? indicatorKey;

  return (
    <div className="flex flex-col gap-2">
      <header className="flex flex-wrap items-center justify-end gap-2">
        <IndicatorRangeSelector
          value={range}
          onChange={setRange}
          indicatorLabel={`${title} 區間`}
        />
      </header>
      {query.isLoading && (
        <div className="flex items-center gap-2 text-xs text-stone-500">
          <LoadingSpinner label="載入中…" />
        </div>
      )}
      {query.isError && (
        <p role="alert" className="text-xs text-rose-700">
          走勢資料載入失敗
        </p>
      )}
      {query.data && (
        <MacroChart data={query.data} ariaLabel={`${title} 走勢圖`} />
      )}
    </div>
  );
}

function rangeToParam(range: MarketIndicatorRangeKey): number | 'all' {
  if (range === 'ALL') return 'all';
  return MARKET_INDICATOR_RANGES.find((r) => r.key === range)?.days ?? 60;
}

function defaultRangeForIndicator(indicatorKey: string): MarketIndicatorRangeKey {
  const tf = INDICATOR_TIMEFRAMES[indicatorKey];
  if (tf === 'short') return '1M';
  if (tf === 'long') return '1Y';
  return '3M';
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
    case 'rsi': {
      // Auto-fit within RSI's hard 0/100 domain so a stock that's spent
      // the whole window in 40-60 doesn't render with 80% of vertical
      // space empty.
      const { yMin, yMax } = computeYBounds(data.series, ['daily', 'weekly'], {
        softMin: 0,
        softMax: 100,
      });
      return (
        <IndicatorBoundedLine
          series={data.series}
          lines={RSI_LINES}
          thresholds={RSI_THRESHOLDS}
          yAxisMin={yMin}
          yAxisMax={yMax}
          ariaLabel={ariaLabel}
        />
      );
    }
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
          upColor="#059669"
          downColor="#e11d48"
          flatColor="#a8a29e"
          averageLineColor="#d97706"
          ariaLabel={ariaLabel}
        />
      );
    case 'relative_strength': {
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
    case 'adx': {
      // ADX is naturally 0-100 but most stocks live below 50. Floor at 0
      // (semantic minimum), let the upper bound follow the actual peak so
      // a stock that never crosses 25 doesn't waste 60% of the chart.
      const { yMin, yMax } = computeYBounds(
        data.series,
        ['adx', 'plus_di', 'minus_di'],
        { softMin: 0 },
      );
      return (
        <IndicatorBoundedLine
          series={data.series}
          lines={ADX_LINES}
          thresholds={ADX_THRESHOLDS}
          yAxisMin={yMin}
          yAxisMax={yMax}
          ariaLabel={ariaLabel}
        />
      );
    }
    case 'atr': {
      // ATR % naturally ≥ 0. Let the percentile auto-fit handle the
      // ceiling — blue chips render around 1-3 %, penny stocks 8-12 %,
      // both well-fitted without manual heuristics.
      const { yMin, yMax } = computeYBounds(data.series, ['atr_pct'], {
        softMin: 0,
      });
      return (
        <IndicatorBoundedLine
          series={data.series}
          lines={ATR_LINES}
          thresholds={ATR_THRESHOLDS}
          yAxisMin={yMin}
          yAxisMax={yMax}
          ariaLabel={ariaLabel}
        />
      );
    }
    case 'ttm_squeeze': {
      const series: ReadonlyArray<MultiLineSeriesRow> = data.series.map((row) => ({
        date: row.date,
        momentum: row.momentum,
      }));
      return (
        <IndicatorMultiLine
          series={series}
          lines={TTM_MOMENTUM_LINES}
          histogram={TTM_MOMENTUM_HISTOGRAM}
          priceFormatter={formatPercent}
          ariaLabel={ariaLabel}
        />
      );
    }
    case 'cho':
      return (
        <IndicatorMultiLine
          series={data.series}
          lines={CHO_LINES}
          priceFormatter={formatMagnitude}
          ariaLabel={ariaLabel}
        />
      );
  }
}

interface MacroChartProps {
  data: import('../api/marketIndicatorSeries').MarketIndicatorSeriesResponse;
  ariaLabel: string;
}

function MacroChart({ data, ariaLabel }: MacroChartProps): JSX.Element | null {
  // DXY + Fed Rate ship different field shapes — DXY has level/ma20 lines,
  // Fed Rate has a single `rate`. Reuse the multi-line primitive with the
  // right key map per indicator so the styling stays consistent.
  switch (data.indicator) {
    case 'dxy':
      return (
        <IndicatorMultiLine
          series={data.series}
          lines={[
            { key: 'level', label: 'DXY', color: '#0284c7', width: 2 },
            { key: 'ma20', label: '20 MA', color: '#d97706', style: 'dashed', width: 1 },
          ]}
          ariaLabel={ariaLabel}
        />
      );
    case 'fed_rate':
      return (
        <IndicatorMultiLine
          series={data.series}
          lines={[
            { key: 'rate', label: 'Fed 利率 (%)', color: '#8b5cf6', width: 2 },
          ]}
          ariaLabel={ariaLabel}
        />
      );
    default:
      return null;
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
