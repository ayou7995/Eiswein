import { useMemo } from 'react';
import { Link } from 'react-router-dom';
import { LoadingSpinner } from '../components/LoadingSpinner';
import { ActionBadge } from '../components/ActionBadge';
import {
  MarketRegimeIndicatorList,
  type ChartNameResolver,
} from '../components/MarketRegimeIndicatorList';
import { DataFreshnessBadge } from '../components/DataFreshnessBadge';
import { IndicatorDriftBanner } from '../components/IndicatorDriftBanner';
import { Explainable, RuleTable } from '../components/Explainable';
import { useMarketPosture } from '../hooks/useMarketPosture';
import { useSystemInfo } from '../hooks/useSettings';
import { marketIndicatorSeriesNameSchema } from '../api/marketIndicatorSeries';
import { useDashboardWatchlistSignals } from '../hooks/useDashboardWatchlistSignals';
import type { ActionCategoryCode } from '../api/tickerSignal';
import type { ProsConsItem } from '../api/prosCons';
import { EisweinApiError } from '../api/errors';
import { ROUTES } from '../lib/constants';

// Bento layout — Commit C redesign. Replaces the dashboard's stacked
// posture/macro/attention/watchlist cards with:
//   1. Hero card (full-width) — big posture label + streak + counts
//   2. 4-up grid — regime indicators (VIX / A/D Day / SPX MA / 10Y-2Y)
//   3. 總經背景 row — DXY + Fed Rate (don't vote in posture)
//   4. 需要留意 banner — top-N tickers needing action
// Watchlist navigation is now sidebar-only; the "所有觀察標的" overview
// table is removed.

const REGIME_ORDER: ReadonlyArray<string> = ['vix', 'ad_day', 'spx_ma', 'yield_spread'];
const MACRO_BACKDROP_NAMES: ReadonlySet<string> = new Set(['dxy', 'fed_rate']);
const ATTENTION_ACTIONS: readonly ActionCategoryCode[] = [
  'strong_buy',
  'reduce',
  'exit',
];

const MACRO_CHART_NAME: ChartNameResolver = (indicatorName) => {
  if (indicatorName === 'dxy') return 'dxy';
  if (indicatorName === 'fed_rate') return 'fed_rate';
  return null;
};

const POSTURE_TINT: Record<string, string> = {
  offensive: 'bg-emerald-50 border-emerald-200',
  normal: 'bg-sky-50 border-sky-200',
  defensive: 'bg-rose-50 border-rose-200',
};

export function MarketOverviewPage(): JSX.Element {
  return (
    <div className="flex flex-col gap-6">
      <IndicatorDriftBanner />
      <PageHeader />
      <HeroCard />
      <RegimeIndicatorsGrid />
      <MacroBackdropCard />
      <AttentionAlertsBanner />
    </div>
  );
}

function PageHeader(): JSX.Element {
  const { data: sysInfo } = useSystemInfo();
  return (
    <header
      aria-labelledby="market-overview-heading"
      className="flex flex-wrap items-end justify-between gap-3"
    >
      <div>
        <h1
          id="market-overview-heading"
          className="text-2xl font-bold tracking-tight text-stone-900"
        >
          市場總覽
        </h1>
        <p className="text-xs text-stone-500">
          所有數據基於最近交易日收盤後重算。市場態勢為全體共享狀態。
        </p>
      </div>
      {sysInfo?.data_freshness && (
        <DataFreshnessBadge freshness={sysInfo.data_freshness} />
      )}
    </header>
  );
}

function HeroCard(): JSX.Element {
  const { data, isLoading, isError, error, refetch } = useMarketPosture();
  if (isLoading) {
    return (
      <section
        data-testid="hero-card-loading"
        className="flex h-[140px] items-center justify-center rounded-2xl border border-stone-200 bg-white"
      >
        <div className="flex items-center gap-2 text-stone-500">
          <LoadingSpinner label="載入市場態勢…" />
          <span className="text-sm">載入市場態勢…</span>
        </div>
      </section>
    );
  }
  if (error instanceof EisweinApiError && error.status === 404) {
    return (
      <section className="flex h-[140px] items-center justify-center rounded-2xl border border-stone-200 bg-white text-sm text-stone-500">
        <p role="status">等待首次運算（每日收盤後產出）。</p>
      </section>
    );
  }
  if (isError || !data) {
    return (
      <section className="flex h-[140px] items-center justify-between rounded-2xl border border-rose-300 bg-rose-50 px-6 text-sm text-rose-700">
        <span>無法載入市場態勢。</span>
        <button
          type="button"
          onClick={() => void refetch()}
          className="underline"
        >
          重試
        </button>
      </section>
    );
  }
  const tint = POSTURE_TINT[data.posture] ?? 'bg-sky-50 border-sky-200';
  return (
    <section
      aria-labelledby="hero-posture-heading"
      className={`flex flex-col gap-2 rounded-2xl border p-6 ${tint}`}
    >
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h2
            id="hero-posture-heading"
            className="text-3xl font-bold text-stone-900"
          >
            <Explainable
              title="市場態勢判定規則"
              marker="none"
              explanation={
                <RuleTable
                  preface="由 4 個市場態勢指標（SPX 多頭排列、A/D Day、VIX、10Y-2Y 利差）的紅綠燈計票決定。資料不足的指標不算票；4 個全部不足 → 預設為「正常」。"
                  rows={[
                    {
                      condition: '綠燈 ≥ 3',
                      result: '✨ 進攻（多數指標看多，可考慮加碼）',
                      current: data.regime_green_count >= 3,
                    },
                    {
                      condition: '紅燈 ≥ 2',
                      result: '🛡 防守（多數指標看空，謹慎為上）',
                      current: data.regime_red_count >= 2,
                    },
                    {
                      condition: '其他',
                      result: '⚖ 正常（無明顯偏向，照常操作）',
                      current:
                        data.regime_green_count < 3 && data.regime_red_count < 2,
                    },
                  ]}
                  currentValueText={`你目前: 綠 ${data.regime_green_count} · 黃 ${data.regime_yellow_count} · 紅 ${data.regime_red_count} → 市場態勢：${data.posture_label}`}
                  note="DXY 與 Fed 利率屬「總經背景」，不投票進市場態勢；下方獨立區塊顯示。"
                />
              }
            >
              <span data-testid="market-posture-label">
                市場態勢：{data.posture_label}
              </span>
            </Explainable>
          </h2>
          <p className="text-sm text-stone-600">
            {data.streak_badge ? (
              <span>{data.streak_badge} · </span>
            ) : (
              <span>連續 {data.streak_days} 天 · </span>
            )}
            <span>全體共享</span>
            <span className="ml-2 text-xs text-stone-500">
              最近交易日：{data.date}
            </span>
          </p>
        </div>
        <div className="flex items-center gap-2">
          <CountChip color="emerald" label="買" count={data.regime_green_count} />
          <CountChip color="amber" label="持" count={data.regime_yellow_count} />
          <CountChip color="rose" label="賣" count={data.regime_red_count} />
        </div>
      </div>
    </section>
  );
}

interface CountChipProps {
  color: 'emerald' | 'amber' | 'rose';
  label: string;
  count: number;
}

const CHIP_TONE: Record<CountChipProps['color'], string> = {
  emerald: 'bg-emerald-100 text-emerald-800 border-emerald-200',
  amber: 'bg-amber-100 text-amber-800 border-amber-200',
  rose: 'bg-rose-100 text-rose-800 border-rose-200',
};

function CountChip({ color, label, count }: CountChipProps): JSX.Element {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-sm font-semibold ${CHIP_TONE[color]}`}
    >
      <span>{label}</span>
      <span className="font-mono tabular-nums">{count}</span>
    </span>
  );
}

function RegimeIndicatorsGrid(): JSX.Element {
  const { data, isLoading } = useMarketPosture();
  const items = useMemo(() => {
    if (!data) return [];
    return data.pros_cons
      .filter(
        (item) =>
          marketIndicatorSeriesNameSchema.safeParse(item.indicator_name).success,
      )
      .slice()
      .sort(
        (a, b) =>
          REGIME_ORDER.indexOf(a.indicator_name) -
          REGIME_ORDER.indexOf(b.indicator_name),
      );
  }, [data]);

  if (isLoading) return <p className="text-xs text-stone-500">載入指標…</p>;
  if (items.length === 0) return <></>;

  return (
    <section
      aria-labelledby="regime-indicators-heading"
      className="rounded-2xl border border-stone-200 bg-white p-6"
    >
      <header className="mb-3">
        <h2
          id="regime-indicators-heading"
          className="text-base font-semibold text-stone-900"
        >
          4 個市場態勢指標
        </h2>
      </header>
      <MarketRegimeIndicatorList items={items} />
    </section>
  );
}

function MacroBackdropCard(): JSX.Element {
  const { rows } = useDashboardWatchlistSignals();
  const macroItems = useMemo<readonly ProsConsItem[]>(() => {
    const firstReady = rows.find((r) => r.status === 'ready' && r.signal !== null);
    if (!firstReady?.signal) return [];
    return firstReady.signal.pros_cons.filter((item) =>
      MACRO_BACKDROP_NAMES.has(item.indicator_name),
    );
  }, [rows]);

  return (
    <section
      aria-labelledby="macro-backdrop-heading"
      className="rounded-2xl border border-stone-200 bg-white p-6"
    >
      <header className="mb-3">
        <h2
          id="macro-backdrop-heading"
          className="text-base font-semibold text-stone-900"
        >
          總經背景
        </h2>
        <p className="text-xs text-stone-500">
          美元指數與 Fed 利率的當前讀數；不直接進入市場態勢投票。
        </p>
      </header>
      {macroItems.length === 0 ? (
        <p role="status" className="text-sm text-stone-500">
          等待首次運算（需要至少一個觀察清單標的完成分析）。
        </p>
      ) : (
        <MarketRegimeIndicatorList
          items={macroItems}
          resolveChartName={MACRO_CHART_NAME}
        />
      )}
    </section>
  );
}

function AttentionAlertsBanner(): JSX.Element {
  const { rows, watchlistLoading } = useDashboardWatchlistSignals();
  const attention = useMemo(
    () =>
      rows.filter(
        (row) =>
          row.status === 'ready' &&
          row.signal !== null &&
          ATTENTION_ACTIONS.includes(row.signal.action),
      ),
    [rows],
  );

  if (watchlistLoading) {
    return (
      <section
        aria-labelledby="attention-heading"
        className="rounded-2xl border border-stone-200 bg-white p-4"
      >
        <h2 id="attention-heading" className="text-base font-semibold">
          需要留意
        </h2>
        <p className="mt-2 text-sm text-stone-500">載入中…</p>
      </section>
    );
  }

  if (attention.length === 0) {
    return (
      <section
        aria-labelledby="attention-heading"
        className="rounded-2xl border border-stone-200 bg-white p-4"
      >
        <h2 id="attention-heading" className="text-base font-semibold">
          <Explainable
            title="「需要留意」篩選規則"
            explanation={
              <RuleTable
                preface="觀察清單中當日 action 屬下列三類的標的會跳到這裡，是「需要當下做決定」的高警示訊號。中間 3 種（買入 / 持有 / 觀望）不跳——日常已知狀態，不需特別 alert。"
                rows={[
                  {
                    condition: '🟢🟢 強力買入',
                    result: '4 個方向指標全綠，買進機會浮現',
                  },
                  { condition: '⚠️ 減倉', result: '紅燈 2-3 個，趨勢轉弱，考慮部分出場' },
                  { condition: '🔴🔴 出場', result: '4 個方向指標全紅，趕快出' },
                ]}
                note="篩選清單為空 → 沒有需要立即關注的訊號。"
              />
            }
          >
            需要留意
          </Explainable>
        </h2>
        <p className="mt-2 text-sm text-stone-500">沒有需要立即關注的訊號。</p>
      </section>
    );
  }

  return (
    <section
      aria-labelledby="attention-heading"
      className="rounded-2xl border border-amber-300 bg-amber-50 p-4"
    >
      <header className="flex items-center justify-between gap-3">
        <h2 id="attention-heading" className="text-base font-semibold text-amber-900">
          <Explainable
            title="「需要留意」篩選規則"
            explanation={
              <RuleTable
                preface="觀察清單中當日 action 屬下列三類的標的會跳到這裡。"
                rows={[
                  {
                    condition: '🟢🟢 強力買入',
                    result: '4 個方向指標全綠',
                  },
                  { condition: '⚠️ 減倉', result: '紅燈 2-3 個' },
                  { condition: '🔴🔴 出場', result: '4 個方向指標全紅' },
                ]}
              />
            }
          >
            需要留意
          </Explainable>
        </h2>
        <span className="text-xs text-amber-700">{attention.length} 個標的</span>
      </header>
      <ul
        className="mt-2 flex flex-wrap items-center gap-2"
        data-testid="attention-list"
      >
        {attention.map((row) => {
          const signal = row.signal;
          if (!signal) return null;
          return (
            <li key={row.item.symbol}>
              <Link
                to={ROUTES.TICKER.replace(':symbol', row.item.symbol)}
                className="inline-flex items-center gap-2 rounded-full border border-amber-300 bg-white px-3 py-1 text-sm hover:border-amber-400 hover:bg-amber-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500"
              >
                <span className="font-mono font-semibold text-stone-900">
                  {row.item.symbol}
                </span>
                <ActionBadge
                  action={signal.action}
                  timingBadge={signal.timing_badge}
                />
              </Link>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
