import { useState } from 'react';
import type { ProsConsItem } from '../api/prosCons';
import {
  DEFAULT_RANGE_BY_INDICATOR,
  MARKET_INDICATOR_RANGES,
  marketIndicatorSeriesNameSchema,
  type MarketIndicatorRangeKey,
  type MarketIndicatorSeriesName,
  type MarketIndicatorSeriesResponse,
} from '../api/marketIndicatorSeries';
import { useMarketIndicatorSeries } from '../hooks/useMarketIndicatorSeries';
import { computeYBounds } from '../lib/yAxisAutoFit';
import { StalenessPill } from './StalenessPill';
import { IndicatorRangeSelector } from './IndicatorRangeSelector';
import { LoadingSpinner } from './LoadingSpinner';
import { TimeframeChip } from './TimeframeChip';
import { IndicatorMultiLine } from './charts/IndicatorMultiLine';
import { IndicatorBoundedLine } from './charts/IndicatorBoundedLine';
import { AdDayCandleClassificationChart } from './charts/AdDayCandleClassificationChart';
import { YieldSpreadDualPaneChart } from './charts/YieldSpreadDualPaneChart';
import {
  MaPositionEnhancedDetail,
  MaPositionHeadlineExplainable,
} from './MaPositionEnhancedDetail';
import {
  VixEnhancedDetail,
  VixHeadlineExplainable,
} from './VixEnhancedDetail';
import {
  AdDayEnhancedDetail,
  AdDayHeadlineExplainable,
} from './AdDayEnhancedDetail';
import {
  YieldSpreadEnhancedDetail,
  YieldSpreadHeadlineExplainable,
} from './YieldSpreadEnhancedDetail';
import {
  DxyEnhancedDetail,
  DxyHeadlineExplainable,
} from './DxyEnhancedDetail';
import {
  FedRateEnhancedDetail,
  FedRateHeadlineExplainable,
} from './FedRateEnhancedDetail';
import {
  AdxEnhancedDetail,
  AdxHeadlineExplainable,
} from './AdxEnhancedDetail';
import {
  VixTermEnhancedDetail,
  VixTermHeadlineExplainable,
} from './VixTermEnhancedDetail';
import {
  AdLineEnhancedDetail,
  AdLineHeadlineExplainable,
} from './AdLineEnhancedDetail';

const SPX_MA_HEADLINE_LABELS = {
  ruleTitle: 'SPX 紅黃綠燈規則',
  ruleNote:
    '此燈號是「中期市場態勢」4 票之 1(綠/紅/黃 → 進攻/防守/正常)。只投中期,不投短期 posture。',
};

const VIX_HEADLINE_LABELS = {
  ruleTitle: 'VIX 紅黃綠燈規則',
  ruleNote:
    '此燈號是 dual-vote 成員 — 同時投中期 4 票 + 短期 3 票。VIX 過低 (<12) 是反向訊號:市場過於自滿時反轉風險升高。短期 posture 用 3 vote (vix + ad_day + vix_term),中期 posture 用 4 vote (vix + ad_day + spx_ma + yield_spread)。',
};

const AD_DAY_HEADLINE_LABELS = {
  ruleTitle: 'A/D Day 紅黃綠燈規則',
  ruleNote:
    '此燈號是 dual-vote 成員 — 同時投中期 4 票 + 短期 3 票。進貨/出貨日須伴隨「量擴大」才計入 — 大資金需要量才能動倉。⚠ 「過去 25 天」是 O\'Neil 定義的固定窗口,不會跟著下方圖表 range 改變;range 只影響顯示多少根歷史 K 線。',
};

const YIELD_SPREAD_HEADLINE_LABELS = {
  ruleTitle: '10Y-2Y 利差紅黃綠燈規則',
  ruleNote:
    '此燈號是「中期市場態勢」4 票之 1。只投中期,不投短期 posture。倒掛 (spread<0) 是衰退領先指標,過去 5 次衰退都先見倒掛、衰退實際發生在倒掛結束後 6-18 個月。',
};

const DXY_HEADLINE_LABELS = {
  ruleTitle: 'DXY 紅黃綠燈規則',
  ruleNote:
    'DXY 是美元指數。「總經背景」之一，不投市場態勢票。與科技股呈反向關係 — 美元走強時資金流出科技股、走弱時相反。',
};

const FED_RATE_HEADLINE_LABELS = {
  ruleTitle: 'Fed 利率紅黃綠燈規則',
  ruleNote:
    'Fed Funds Rate 是聯邦基金利率。「總經背景」之一，不投市場態勢票。降息提升風險資產估值（對股市友善），升息相反。',
};

const SPX_ADX_HEADLINE_LABELS = {
  ruleTitle: 'SPX ADX 趨勢強度紅黃綠燈規則',
  ruleNote:
    '此燈號是獨立的「大盤趨勢強度」讀數,跟 SPX 50/200 MA(方向)互補但不修飾彼此。SPX ADX ≥ 25 + SPX 站上 200MA = 上升趨勢有量、值得參與;SPX ADX < 20 = 大盤盤整,持倉先觀望。+DI / -DI 顯示偏多或偏空。',
};

const VIX_TERM_HEADLINE_LABELS = {
  ruleTitle: 'VIX 期限結構紅黃綠燈規則',
  ruleNote:
    '此燈號是「短期市場態勢」3 票之 1。只投短期,不投中期 posture。比 VIX 絕對值更敏感於市場結構性轉變 — VIX 22 可能是平日震盪,但若同時 VIX > VIX3M,代表「現在恐慌已強過 3 個月遠期」,通常是真正壓力的開端。',
};

const AD_LINE_HEADLINE_LABELS = {
  ruleTitle: '觀察名單 A/D Line 紅黃綠燈規則',
  ruleNote:
    '此燈號是「廣度健康度檢查」— 個人化版本的 NYSE 廣度指標,範圍是所有使用者 watchlist 的並集。窄漲 (SPX 上但 AD Line 下) = 警示;同步上升 = 健康行情。不投正式 posture 票。⚠ 加入/移除 watchlist 標的會回溯改變歷史值 — 兩個不同時間點的截圖不一定能對得起來。',
};

const TONE_DOT: Record<ProsConsItem['tone'], { emoji: string; ariaLabel: string }> = {
  pro: { emoji: '🟢', ariaLabel: '利多訊號' },
  con: { emoji: '🔴', ariaLabel: '利空訊號' },
  neutral: { emoji: '⚪', ariaLabel: '中性或資料不足' },
};

function humanizeKey(key: string): string {
  return key.replace(/_/g, ' ');
}

function renderValue(value: unknown): string {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'boolean') return value ? '是' : '否';
  if (typeof value === 'number') {
    if (Number.isInteger(value)) return String(value);
    return Number.parseFloat(value.toFixed(4)).toString();
  }
  if (typeof value === 'string') return value;
  return JSON.stringify(value);
}

export type ChartNameResolver = (
  indicatorName: string,
) => MarketIndicatorSeriesName | null;

export interface MarketRegimeIndicatorListProps {
  items: readonly ProsConsItem[];
  emptyMessage?: string;
  // Allows callers to surface chart-able indicators whose pros_cons
  // indicator_name differs from the chart-endpoint slug (e.g. macro 'dxy'
  // → chart 'dxy_trend'). Defaults to identity-via-enum-validation.
  resolveChartName?: ChartNameResolver;
  // The market snapshot's trade_date — used by the per-row StalenessPill
  // to detect when an indicator's underlying data lags the snapshot.
  snapshotDate?: string | null;
}

export function MarketRegimeIndicatorList({
  items,
  emptyMessage = '資料不足以判斷',
  resolveChartName = parseChartName,
  snapshotDate = null,
}: MarketRegimeIndicatorListProps): JSX.Element {
  if (items.length === 0) {
    return (
      <p role="status" className="text-sm text-stone-500">
        {emptyMessage}
      </p>
    );
  }

  return (
    <ul className="grid grid-cols-1 gap-3 md:grid-cols-2">
      {items.map((item) => (
        <RegimeRow
          key={item.indicator_name}
          item={item}
          resolveChartName={resolveChartName}
          snapshotDate={snapshotDate}
        />
      ))}
    </ul>
  );
}

interface RegimeRowProps {
  item: ProsConsItem;
  resolveChartName: ChartNameResolver;
  snapshotDate: string | null;
}

function RegimeRow({
  item,
  resolveChartName,
  snapshotDate,
}: RegimeRowProps): JSX.Element {
  // Indicator details are always shown inline — no collapse mechanism.
  // Charts load eagerly on mount via ``useMarketIndicatorSeries`` inside
  // ``RegimeChartSection``; with 4-6 cards per page the parallel queries
  // are well within TanStack Query's batching budget.
  const tone = TONE_DOT[item.tone];
  const detailEntries = Object.entries(item.detail);

  const chartName = resolveChartName(item.indicator_name);

  return (
    <li
      id={`regime-${item.indicator_name}`}
      data-testid="regime-row"
      className="flex flex-col overflow-hidden rounded-md border border-stone-200 bg-white scroll-mt-24"
    >
      <header className="flex items-center gap-2 px-3 py-2 text-sm text-stone-800">
        <span aria-label={tone.ariaLabel}>{tone.emoji}</span>
        <span className="flex-1">
          {item.indicator_name === 'spx_ma' ? (
            <MaPositionHeadlineExplainable
              shortLabel={item.short_label}
              detail={item.detail}
              labels={SPX_MA_HEADLINE_LABELS}
            />
          ) : item.indicator_name === 'vix' ? (
            <VixHeadlineExplainable
              shortLabel={item.short_label}
              detail={item.detail}
              labels={VIX_HEADLINE_LABELS}
            />
          ) : item.indicator_name === 'ad_day' ? (
            <AdDayHeadlineExplainable
              shortLabel={item.short_label}
              detail={item.detail}
              labels={AD_DAY_HEADLINE_LABELS}
            />
          ) : item.indicator_name === 'yield_spread' ? (
            <YieldSpreadHeadlineExplainable
              shortLabel={item.short_label}
              detail={item.detail}
              labels={YIELD_SPREAD_HEADLINE_LABELS}
            />
          ) : item.indicator_name === 'dxy' ? (
            <DxyHeadlineExplainable
              shortLabel={item.short_label}
              detail={item.detail}
              labels={DXY_HEADLINE_LABELS}
            />
          ) : item.indicator_name === 'fed_rate' ? (
            <FedRateHeadlineExplainable
              shortLabel={item.short_label}
              detail={item.detail}
              labels={FED_RATE_HEADLINE_LABELS}
            />
          ) : item.indicator_name === 'spx_adx' ? (
            <AdxHeadlineExplainable
              shortLabel={item.short_label}
              detail={item.detail}
              labels={SPX_ADX_HEADLINE_LABELS}
            />
          ) : item.indicator_name === 'vix_term' ? (
            <VixTermHeadlineExplainable
              shortLabel={item.short_label}
              detail={item.detail}
              labels={VIX_TERM_HEADLINE_LABELS}
            />
          ) : item.indicator_name === 'ad_line' ? (
            <AdLineHeadlineExplainable
              shortLabel={item.short_label}
              detail={item.detail}
              labels={AD_LINE_HEADLINE_LABELS}
            />
          ) : (
            item.short_label
          )}
        </span>
        <TimeframeChip timeframe={item.timeframe} />
        {snapshotDate && (
          <StalenessPill
            dataAsOf={item.data_as_of}
            snapshotDate={snapshotDate}
          />
        )}
      </header>
      <div className="flex flex-col gap-2 border-t border-stone-200 bg-stone-50 p-3">
        {chartName !== null && <RegimeChartSection name={chartName} />}
        {item.indicator_name === 'spx_ma' ? (
          <MaPositionEnhancedDetail detail={item.detail} />
        ) : item.indicator_name === 'vix' ? (
          <VixEnhancedDetail detail={item.detail} />
        ) : item.indicator_name === 'ad_day' ? (
          <AdDayEnhancedDetail detail={item.detail} />
        ) : item.indicator_name === 'yield_spread' ? (
          <YieldSpreadEnhancedDetail detail={item.detail} />
        ) : item.indicator_name === 'dxy' ? (
          <DxyEnhancedDetail detail={item.detail} />
        ) : item.indicator_name === 'fed_rate' ? (
          <FedRateEnhancedDetail detail={item.detail} />
        ) : item.indicator_name === 'spx_adx' ? (
          <AdxEnhancedDetail detail={item.detail} />
        ) : item.indicator_name === 'vix_term' ? (
          <VixTermEnhancedDetail detail={item.detail} />
        ) : item.indicator_name === 'ad_line' ? (
          <AdLineEnhancedDetail detail={item.detail} />
        ) : (
          detailEntries.length > 0 && (
            <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs text-stone-700">
              {detailEntries.map(([key, value]) => (
                <div key={key} className="contents">
                  <dt className="font-mono text-stone-400">{humanizeKey(key)}</dt>
                  <dd className="font-mono text-stone-800">{renderValue(value)}</dd>
                </div>
              ))}
            </dl>
          )
        )}
      </div>
    </li>
  );
}

function parseChartName(indicatorName: string): MarketIndicatorSeriesName | null {
  const result = marketIndicatorSeriesNameSchema.safeParse(indicatorName);
  return result.success ? result.data : null;
}

interface RegimeChartSectionProps {
  name: MarketIndicatorSeriesName;
}

function rangeToParam(range: MarketIndicatorRangeKey): number | 'all' {
  if (range === 'ALL') return 'all';
  return MARKET_INDICATOR_RANGES.find((r) => r.key === range)?.days ?? 60;
}

function RegimeChartSection({ name }: RegimeChartSectionProps): JSX.Element {
  const [range, setRange] = useState<MarketIndicatorRangeKey>(
    DEFAULT_RANGE_BY_INDICATOR[name],
  );
  const { data, isLoading, isError, error, refetch } = useMarketIndicatorSeries(name, {
    days: rangeToParam(range),
  });

  return (
    <div className="flex flex-col gap-2 px-3 py-3">
      <header className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-stone-700">{data?.summary_zh ?? ''}</p>
        <IndicatorRangeSelector value={range} onChange={setRange} indicatorLabel={name} />
      </header>
      {isLoading && (
        <div className="flex items-center gap-2 text-stone-500">
          <LoadingSpinner label="載入指標走勢…" />
          <span className="text-xs">載入中…</span>
        </div>
      )}
      {!isLoading && (isError || !data) && (
        <div className="flex items-center justify-between text-xs text-signal-red">
          <span>無法載入走勢圖。{error instanceof Error ? error.message : ''}</span>
          <button
            type="button"
            onClick={() => void refetch()}
            className="underline hover:text-signal-red"
          >
            重試
          </button>
        </div>
      )}
      {data && <IndicatorChart response={data} />}
    </div>
  );
}

interface IndicatorChartProps {
  response: MarketIndicatorSeriesResponse;
}

function IndicatorChart({ response }: IndicatorChartProps): JSX.Element | null {
  if (response.indicator === 'spx_ma') {
    return (
      <IndicatorMultiLine
        series={response.series}
        lines={[
          { key: 'price', label: 'SPX 收盤', color: '#e2e8f0' },
          { key: 'ma50', label: '50 MA', color: '#38bdf8', style: 'dashed' },
          { key: 'ma200', label: '200 MA', color: '#a855f7', style: 'dashed', width: 1 },
        ]}
        ariaLabel="SPX 與 50/200 日均線走勢"
      />
    );
  }
  if (response.indicator === 'vix') {
    // VIX naturally ≥ 0 but historical spikes hit 82 (2020-03). The
    // percentile auto-fit caps the upper bound on the 98th percentile of
    // the visible window so a single panic day doesn't squash the rest
    // of the chart, but it still extends past the old 50 cap when the
    // selected window contains a real volatility regime.
    const { yMin, yMax } = computeYBounds(response.series, ['level'], {
      softMin: 0,
    });
    return (
      <IndicatorBoundedLine
        series={response.series}
        lines={[{ key: 'level', label: 'VIX', color: '#e2e8f0' }]}
        thresholds={[
          {
            value: response.thresholds.low,
            label: '低恐慌',
            color: '#22c55e',
            fillBetween: 'below',
          },
          {
            value: response.thresholds.normal_high,
            label: '正常上限',
            color: '#eab308',
          },
          {
            value: response.thresholds.elevated_high,
            label: '恐慌',
            color: '#ef4444',
            fillBetween: 'above',
          },
        ]}
        yAxisMin={yMin}
        yAxisMax={yMax}
        ariaLabel="VIX 60 日走勢"
      />
    );
  }
  if (response.indicator === 'yield_spread') {
    return <YieldSpreadDualPaneChart response={response} />;
  }
  if (response.indicator === 'dxy') {
    return (
      <IndicatorMultiLine
        series={response.series}
        lines={[
          { key: 'level', label: 'DXY', color: '#e2e8f0', width: 1 },
          { key: 'ma20', label: '20 日均線', color: '#38bdf8', width: 2 },
        ]}
        ariaLabel="美元指數 60 日走勢"
      />
    );
  }
  if (response.indicator === 'fed_rate') {
    return (
      <IndicatorMultiLine
        series={response.series}
        lines={[
          { key: 'rate', label: 'Fed Funds Rate (%)', color: '#facc15', width: 2, step: true },
        ]}
        ariaLabel="聯邦基金利率 365 日走勢"
      />
    );
  }
  if (response.indicator === 'ad_day') {
    return <AdDayCandleClassificationChart response={response} />;
  }
  if (response.indicator === 'spx_adx') {
    const { yMin, yMax } = computeYBounds(
      response.series,
      ['adx', 'plus_di', 'minus_di'],
      { softMin: 0 },
    );
    return (
      <IndicatorBoundedLine
        series={response.series}
        lines={[
          { key: 'adx', label: 'ADX', color: '#e2e8f0' },
          { key: 'plus_di', label: '+DI', color: '#22c55e' },
          { key: 'minus_di', label: '-DI', color: '#ef4444' },
        ]}
        thresholds={[
          {
            value: response.thresholds.no_trend,
            label: '盤整 (<20)',
            color: '#a1a1aa',
            fillBetween: 'below',
          },
          {
            value: response.thresholds.trend,
            label: '強趨勢 (≥25)',
            color: '#22c55e',
            fillBetween: 'above',
          },
        ]}
        yAxisMin={yMin}
        yAxisMax={yMax}
        ariaLabel="SPX ADX 60 日走勢"
      />
    );
  }
  if (response.indicator === 'vix_term') {
    // VIX/VIX3M historically rangebound 0.7-1.0 in calm regimes; spikes
    // past 1.5 during 2020-03 and 2023-10 stress events. Auto-fit so
    // those structural inversions remain visible on long ranges.
    const { yMin, yMax } = computeYBounds(response.series, ['ratio'], {
      softMin: 0,
    });
    return (
      <IndicatorBoundedLine
        series={response.series}
        lines={[{ key: 'ratio', label: 'VIX / VIX3M', color: '#1c1917' }]}
        thresholds={[
          {
            value: response.thresholds.contango,
            label: 'contango (<0.95)',
            color: '#22c55e',
            fillBetween: 'below',
          },
          {
            value: response.thresholds.inversion,
            label: '倒掛 (≥1.0)',
            color: '#ef4444',
            fillBetween: 'above',
          },
        ]}
        yAxisMin={yMin}
        yAxisMax={yMax}
        ariaLabel="VIX 期限結構比 60 日走勢"
      />
    );
  }
  if (response.indicator === 'ad_line') {
    return (
      <IndicatorMultiLine
        series={response.series}
        lines={[{ key: 'ad_line', label: '累積 AD Line', color: '#0284c7', width: 2 }]}
        ariaLabel="觀察名單 AD Line 60 日走勢"
      />
    );
  }
  // Discriminated-union exhaustiveness — should be unreachable.
  return null;
}
