import { useState } from 'react';
import type { ProsConsItem } from '../api/prosCons';
import {
  marketIndicatorSeriesNameSchema,
  type MarketIndicatorSeriesName,
  type MarketIndicatorSeriesResponse,
} from '../api/marketIndicatorSeries';
import { useMarketIndicatorSeries } from '../hooks/useMarketIndicatorSeries';
import { LoadingSpinner } from './LoadingSpinner';
import { IndicatorMultiLine } from './charts/IndicatorMultiLine';
import { IndicatorBoundedLine } from './charts/IndicatorBoundedLine';
import { IndicatorCategoricalBars } from './charts/IndicatorCategoricalBars';
import {
  MaPositionEnhancedDetail,
  MaPositionHeadlineExplainable,
} from './MaPositionEnhancedDetail';
import {
  VixEnhancedDetail,
  VixHeadlineExplainable,
} from './VixEnhancedDetail';

const SPX_MA_HEADLINE_LABELS = {
  ruleTitle: 'SPX 紅黃綠燈規則',
  ruleNote:
    '此燈號是市場態勢 4 票之 1（綠/紅/黃 → 進攻/防守/正常）；展開列可看距離尺標與看點。',
};

const VIX_HEADLINE_LABELS = {
  ruleTitle: 'VIX 紅黃綠燈規則',
  ruleNote:
    '此燈號是市場態勢 4 票之 1。VIX 過低 (<12) 是反向訊號：市場過於自滿時反轉風險升高。',
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
}

export function MarketRegimeIndicatorList({
  items,
  emptyMessage = '資料不足以判斷',
  resolveChartName = parseChartName,
}: MarketRegimeIndicatorListProps): JSX.Element {
  if (items.length === 0) {
    return (
      <p role="status" className="text-sm text-slate-400">
        {emptyMessage}
      </p>
    );
  }

  return (
    <ul className="flex flex-col divide-y divide-slate-800 overflow-hidden rounded-md border border-slate-800">
      {items.map((item) => (
        <RegimeRow
          key={item.indicator_name}
          item={item}
          resolveChartName={resolveChartName}
        />
      ))}
    </ul>
  );
}

interface RegimeRowProps {
  item: ProsConsItem;
  resolveChartName: ChartNameResolver;
}

function RegimeRow({ item, resolveChartName }: RegimeRowProps): JSX.Element {
  // The chart is lazy-loaded: useMarketIndicatorSeries is gated on `enabled`,
  // and `enabled` flips true the first time the user expands this row.
  const [hasOpened, setHasOpened] = useState(false);
  const tone = TONE_DOT[item.tone];
  const detailEntries = Object.entries(item.detail);

  const chartName = resolveChartName(item.indicator_name);

  return (
    <li className="bg-slate-900/40">
      <details
        onToggle={(event) => {
          if ((event.currentTarget as HTMLDetailsElement).open) {
            setHasOpened(true);
          }
        }}
      >
        <summary
          data-testid="regime-row-summary"
          className="flex cursor-pointer items-center gap-2 px-3 py-2 text-sm text-slate-200 hover:text-white"
        >
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
            ) : (
              item.short_label
            )}
          </span>
          {(detailEntries.length > 0 || chartName !== null) && (
            <span aria-hidden="true" className="text-xs text-slate-500">
              詳細
            </span>
          )}
        </summary>
        <div className="border-t border-slate-800 bg-slate-950/40">
          {chartName !== null && hasOpened && <RegimeChartSection name={chartName} />}
          {item.indicator_name === 'spx_ma' ? (
            <MaPositionEnhancedDetail detail={item.detail} />
          ) : item.indicator_name === 'vix' ? (
            <VixEnhancedDetail detail={item.detail} />
          ) : (
            detailEntries.length > 0 && (
              <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 px-3 py-2 text-xs text-slate-300">
                {detailEntries.map(([key, value]) => (
                  <div key={key} className="contents">
                    <dt className="font-mono text-slate-500">{humanizeKey(key)}</dt>
                    <dd className="font-mono text-slate-200">{renderValue(value)}</dd>
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

function parseChartName(indicatorName: string): MarketIndicatorSeriesName | null {
  const result = marketIndicatorSeriesNameSchema.safeParse(indicatorName);
  return result.success ? result.data : null;
}

interface RegimeChartSectionProps {
  name: MarketIndicatorSeriesName;
}

function RegimeChartSection({ name }: RegimeChartSectionProps): JSX.Element {
  const { data, isLoading, isError, error, refetch } = useMarketIndicatorSeries(name);

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 px-3 py-3 text-slate-400">
        <LoadingSpinner label="載入指標走勢…" />
        <span className="text-xs">載入中…</span>
      </div>
    );
  }
  if (isError || !data) {
    return (
      <div className="flex items-center justify-between px-3 py-3 text-xs text-signal-red">
        <span>無法載入走勢圖。{error instanceof Error ? error.message : ''}</span>
        <button
          type="button"
          onClick={() => void refetch()}
          className="underline hover:text-signal-red"
        >
          重試
        </button>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2 px-3 py-3">
      <p className="text-xs text-slate-300">{data.summary_zh}</p>
      <IndicatorChart response={data} />
    </div>
  );
}

interface IndicatorChartProps {
  response: MarketIndicatorSeriesResponse;
}

function IndicatorChart({ response }: IndicatorChartProps): JSX.Element {
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
        yAxisMin={0}
        yAxisMax={50}
        ariaLabel="VIX 60 日走勢"
      />
    );
  }
  if (response.indicator === 'yield_spread') {
    return (
      <IndicatorBoundedLine
        series={response.series}
        lines={[{ key: 'spread', label: '10Y-2Y 利差 (%)', color: '#e2e8f0' }]}
        thresholds={[
          {
            value: 0,
            label: '倒掛線',
            color: '#ef4444',
            fillBetween: 'below',
          },
        ]}
        ariaLabel="10Y-2Y 利差 60 日走勢"
      />
    );
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
  return (
    <IndicatorCategoricalBars
      series={response.series}
      colors={{
        accum: '#22c55e',
        distrib: '#ef4444',
        neutral: '#475569',
      }}
      legendLabels={{
        accum: '進貨日',
        distrib: '出貨日',
        neutral: '中性',
      }}
      ariaLabel="A/D Day 25 日分類"
    />
  );
}
