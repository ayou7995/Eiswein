import { useMemo, useRef, useState, type MouseEvent } from 'react';
import type { PostureHistoryItem } from '../../api/history';

// SPY price line on top, posture-tinted background bands behind, color
// stripe at the bottom acting as a compact time map. Hover surfaces a
// 4-indicator breakdown so the user can read why a given day was tagged
// the way it was. Implemented with raw SVG (rather than
// lightweight-charts) because the layout is a single line + colored
// rects, and SVG gives the cleanest control over the per-day
// background bands a regime overlay needs.

export interface PostureTimelineChartProps {
  data: readonly PostureHistoryItem[];
}

const POSTURE_LABEL: Record<PostureHistoryItem['posture'], string> = {
  offensive: '進攻',
  normal: '正常',
  defensive: '防守',
};

const POSTURE_COLOR: Record<PostureHistoryItem['posture'], string> = {
  offensive: '#22c55e',
  normal: '#eab308',
  defensive: '#ef4444',
};

// Tinted variants used as the SPY chart background bands. Lower alpha
// keeps the price line legible on top.
const POSTURE_BAND: Record<PostureHistoryItem['posture'], string> = {
  offensive: 'rgba(34, 197, 94, 0.12)',
  normal: 'rgba(234, 179, 8, 0.10)',
  defensive: 'rgba(239, 68, 68, 0.14)',
};

const SIGNAL_COLOR: Record<string, string> = {
  green: '🟢',
  yellow: '🟡',
  red: '🔴',
  neutral: '⚪',
};

const REGIME_LABEL: Record<string, string> = {
  spx_ma: 'SPX 多頭',
  ad_day: 'A/D Day',
  vix: 'VIX',
  yield_spread: '10Y-2Y',
};

// Render order for the regime indicators inside the hover tooltip.
// Mirrors the dashboard's MarketPostureCard ordering so the user
// learns one stable left-to-right scan.
const REGIME_ORDER: ReadonlyArray<string> = ['spx_ma', 'ad_day', 'vix', 'yield_spread'];

const PRICE_AREA_HEIGHT = 200;
const STRIPE_HEIGHT = 14;
const TOTAL_HEIGHT = PRICE_AREA_HEIGHT + STRIPE_HEIGHT;
// 1px horizontal padding inside the SVG viewBox so the line endpoints
// don't get clipped by the rounded outer border.
const X_PADDING = 1;
// Vertical breathing room between the price extremes and the price-area
// edges so the line never grazes the top/bottom of the chart.
const PRICE_VERTICAL_INSET = 4;

// MA overlay colors. Orange for short-term (50D), blue for long-term
// (200D) — same convention TradingView and yfinance use, so users with
// chart background recognise it instantly.
const MA50_COLOR = '#f59e0b';
const MA200_COLOR = '#60a5fa';

interface HoverInfo {
  index: number;
  clientX: number;
  containerLeft: number;
  containerWidth: number;
}

// Map a price → SVG y-coordinate inside the price area.
function priceToY(price: number, minPrice: number, span: number): number {
  const yRatio = (price - minPrice) / span;
  return (
    PRICE_AREA_HEIGHT - yRatio * (PRICE_AREA_HEIGHT - PRICE_VERTICAL_INSET * 2) - PRICE_VERTICAL_INSET
  );
}

interface PolylineSeries {
  path: string;
}

function buildPolyline(
  points: ReadonlyArray<{ idx: number; value: number | null }>,
  minPrice: number,
  span: number,
): PolylineSeries {
  const segments: string[] = [];
  let current: string[] = [];
  for (const p of points) {
    if (p.value === null) {
      // A null breaks the polyline into a separate segment so missing
      // days create a real gap rather than a misleading flat line.
      if (current.length > 0) {
        segments.push(current.join(' '));
        current = [];
      }
      continue;
    }
    const x = X_PADDING + p.idx;
    const y = priceToY(p.value, minPrice, span);
    current.push(`${x.toFixed(3)},${y.toFixed(3)}`);
  }
  if (current.length > 0) {
    segments.push(current.join(' '));
  }
  return { path: segments.join('  ') };
}

export function PostureTimelineChart({
  data,
}: PostureTimelineChartProps): JSX.Element {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [hover, setHover] = useState<HoverInfo | null>(null);

  const stats = useMemo(() => {
    const counts: Record<PostureHistoryItem['posture'], number> = {
      offensive: 0,
      normal: 0,
      defensive: 0,
    };
    data.forEach((item) => {
      counts[item.posture] += 1;
    });
    const total = data.length;
    const pct = (n: number): number =>
      total === 0 ? 0 : Math.round((n / total) * 1000) / 10;
    return {
      total,
      offensive: counts.offensive,
      normal: counts.normal,
      defensive: counts.defensive,
      offensivePct: pct(counts.offensive),
      normalPct: pct(counts.normal),
      defensivePct: pct(counts.defensive),
    };
  }, [data]);

  // Pre-compute the SPY price polyline + MA overlays in viewBox
  // coordinates so the SVG renderer doesn't have to re-derive them on
  // every mousemove. The Y-axis range covers all three series so the
  // MAs never sail off the visible area.
  const series = useMemo(() => {
    const closeBuf: Array<{ idx: number; value: number | null }> = [];
    const ma50Buf: Array<{ idx: number; value: number | null }> = [];
    const ma200Buf: Array<{ idx: number; value: number | null }> = [];
    const allValues: number[] = [];
    data.forEach((item, idx) => {
      const close = typeof item.spy_close === 'number' ? item.spy_close : null;
      const ma50 = typeof item.spy_ma50 === 'number' ? item.spy_ma50 : null;
      const ma200 = typeof item.spy_ma200 === 'number' ? item.spy_ma200 : null;
      closeBuf.push({ idx, value: close });
      ma50Buf.push({ idx, value: ma50 });
      ma200Buf.push({ idx, value: ma200 });
      if (close !== null) allValues.push(close);
      if (ma50 !== null) allValues.push(ma50);
      if (ma200 !== null) allValues.push(ma200);
    });
    if (allValues.length === 0) {
      return {
        closePath: '',
        ma50Path: '',
        ma200Path: '',
        minPrice: 0,
        maxPrice: 0,
        midPrice: 0,
      };
    }
    const minPrice = Math.min(...allValues);
    const maxPrice = Math.max(...allValues);
    const span = Math.max(maxPrice - minPrice, 0.01);
    return {
      closePath: buildPolyline(closeBuf, minPrice, span).path,
      ma50Path: buildPolyline(ma50Buf, minPrice, span).path,
      ma200Path: buildPolyline(ma200Buf, minPrice, span).path,
      minPrice,
      maxPrice,
      midPrice: (minPrice + maxPrice) / 2,
    };
  }, [data]);

  if (data.length === 0) {
    return (
      <div
        role="status"
        data-testid="posture-timeline-empty"
        className="flex h-32 w-full items-center justify-center rounded-md border border-dashed border-slate-800 bg-slate-900/40 text-sm text-slate-400"
      >
        無市場態勢歷史
      </div>
    );
  }

  const firstDate = data[0]?.date ?? '';
  const lastDate = data[data.length - 1]?.date ?? '';
  const hoveredItem = hover ? data[hover.index] : null;
  // viewBox width grows with data length (one unit per day) plus the
  // 2px horizontal padding band.
  const viewBoxWidth = data.length + X_PADDING * 2;

  // Y positions for the three reference lines (top, mid, bottom of the
  // price range) in viewBox units. These map 1:1 to pixels because
  // preserveAspectRatio="none" combined with the fixed container
  // height keeps Y unstretched.
  const span = Math.max(series.maxPrice - series.minPrice, 0.01);
  const yMaxLine = priceToY(series.maxPrice, series.minPrice, span);
  const yMidLine = priceToY(series.midPrice, series.minPrice, span);
  const yMinLine = priceToY(series.minPrice, series.minPrice, span);

  function handleMove(event: MouseEvent<SVGSVGElement>): void {
    const container = containerRef.current;
    if (!container) return;
    const rect = container.getBoundingClientRect();
    const xRatio = (event.clientX - rect.left) / rect.width;
    const idx = Math.min(
      data.length - 1,
      Math.max(0, Math.floor(xRatio * data.length)),
    );
    setHover({
      index: idx,
      clientX: event.clientX,
      containerLeft: rect.left,
      containerWidth: rect.width,
    });
  }

  return (
    <div
      ref={containerRef}
      className="flex flex-col gap-2"
      data-testid="posture-timeline"
      onMouseLeave={() => setHover(null)}
    >
      <div
        className="relative overflow-hidden rounded-md border border-slate-800 bg-slate-950"
        style={{ height: TOTAL_HEIGHT }}
      >
        <svg
          viewBox={`0 0 ${viewBoxWidth} ${TOTAL_HEIGHT}`}
          preserveAspectRatio="none"
          className="h-full w-full"
          role="img"
          aria-label={`SPY 走勢與市場態勢時間軸，共 ${data.length} 天，由 ${firstDate} 至 ${lastDate}`}
          onMouseMove={handleMove}
        >
          {/* Posture-tinted background bands sitting behind the price line */}
          {data.map((item, idx) => (
            <rect
              key={`band-${item.date}`}
              x={X_PADDING + idx}
              y={0}
              width={1}
              height={PRICE_AREA_HEIGHT}
              fill={POSTURE_BAND[item.posture]}
            />
          ))}
          {/* Y-axis gridlines: top / mid / bottom price reference. */}
          {series.maxPrice > 0 && (
            <>
              <line
                x1={0}
                x2={viewBoxWidth}
                y1={yMaxLine}
                y2={yMaxLine}
                stroke="#1e293b"
                strokeWidth={0.4}
                strokeDasharray="3 3"
                vectorEffect="non-scaling-stroke"
              />
              <line
                x1={0}
                x2={viewBoxWidth}
                y1={yMidLine}
                y2={yMidLine}
                stroke="#1e293b"
                strokeWidth={0.4}
                strokeDasharray="3 3"
                vectorEffect="non-scaling-stroke"
              />
              <line
                x1={0}
                x2={viewBoxWidth}
                y1={yMinLine}
                y2={yMinLine}
                stroke="#1e293b"
                strokeWidth={0.4}
                strokeDasharray="3 3"
                vectorEffect="non-scaling-stroke"
              />
            </>
          )}
          {/* MA200 line — drawn first so the (more emphasized) MA50 and
              SPY close render on top of it. */}
          {series.ma200Path && (
            <polyline
              points={series.ma200Path}
              fill="none"
              stroke={MA200_COLOR}
              strokeOpacity={0.7}
              strokeWidth={0.5}
              vectorEffect="non-scaling-stroke"
            />
          )}
          {series.ma50Path && (
            <polyline
              points={series.ma50Path}
              fill="none"
              stroke={MA50_COLOR}
              strokeOpacity={0.8}
              strokeWidth={0.5}
              vectorEffect="non-scaling-stroke"
            />
          )}
          {/* SPY price line — single polyline so a missing day creates a
              gap rather than a misleading flat segment. */}
          {series.closePath && (
            <polyline
              points={series.closePath}
              fill="none"
              stroke="#e2e8f0"
              strokeWidth={0.6}
              vectorEffect="non-scaling-stroke"
            />
          )}
          {/* Crosshair when hovering */}
          {hover && (
            <line
              x1={X_PADDING + hover.index + 0.5}
              x2={X_PADDING + hover.index + 0.5}
              y1={0}
              y2={PRICE_AREA_HEIGHT}
              stroke="#94a3b8"
              strokeWidth={0.4}
              strokeDasharray="2 2"
              vectorEffect="non-scaling-stroke"
            />
          )}
          {/* Bottom color stripe — the existing compact regime mini-map */}
          {data.map((item, idx) => (
            <rect
              key={`stripe-${item.date}`}
              x={X_PADDING + idx}
              y={PRICE_AREA_HEIGHT}
              width={1}
              height={STRIPE_HEIGHT}
              fill={POSTURE_COLOR[item.posture]}
            >
              <title>
                {item.date} — {POSTURE_LABEL[item.posture]}
              </title>
            </rect>
          ))}
        </svg>
        {/* Y-axis price labels overlaid as HTML so they don't get
            stretched horizontally by preserveAspectRatio="none". */}
        {series.maxPrice > 0 && (
          <>
            <PriceAxisLabel value={series.maxPrice} y={yMaxLine} />
            <PriceAxisLabel value={series.midPrice} y={yMidLine} />
            <PriceAxisLabel value={series.minPrice} y={yMinLine} />
          </>
        )}
        {hoveredItem && hover && (
          <PostureTooltip
            item={hoveredItem}
            clientX={hover.clientX}
            containerLeft={hover.containerLeft}
            containerWidth={hover.containerWidth}
          />
        )}
      </div>
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 text-xs text-slate-400">
        <span>{firstDate}</span>
        <div className="flex items-center gap-3 text-[10px] text-slate-500">
          <LegendDot color="#e2e8f0" label="SPY" />
          <LegendDot color={MA50_COLOR} label="50MA" />
          <LegendDot color={MA200_COLOR} label="200MA" />
        </div>
        <span>{lastDate}</span>
      </div>
      <dl className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
        <StatRow
          label="進攻"
          count={stats.offensive}
          pct={stats.offensivePct}
          color={POSTURE_COLOR.offensive}
        />
        <StatRow
          label="正常"
          count={stats.normal}
          pct={stats.normalPct}
          color={POSTURE_COLOR.normal}
        />
        <StatRow
          label="防守"
          count={stats.defensive}
          pct={stats.defensivePct}
          color={POSTURE_COLOR.defensive}
        />
      </dl>
    </div>
  );
}

interface PriceAxisLabelProps {
  value: number;
  y: number;
}

function PriceAxisLabel({ value, y }: PriceAxisLabelProps): JSX.Element {
  return (
    <span
      aria-hidden="true"
      className="pointer-events-none absolute left-1 rounded bg-slate-950/70 px-1 font-mono text-[10px] text-slate-400"
      style={{
        // The SVG y-coord maps 1:1 to pixels because the container is
        // pinned to TOTAL_HEIGHT. Subtract half the label height so the
        // text sits *on* the gridline, not below it.
        top: `${y - 6}px`,
      }}
    >
      ${value.toFixed(0)}
    </span>
  );
}

interface LegendDotProps {
  color: string;
  label: string;
}

function LegendDot({ color, label }: LegendDotProps): JSX.Element {
  return (
    <span className="flex items-center gap-1">
      <span
        aria-hidden="true"
        className="inline-block h-2 w-3 rounded-sm"
        style={{ backgroundColor: color }}
      />
      <span>{label}</span>
    </span>
  );
}

interface PostureTooltipProps {
  item: PostureHistoryItem;
  clientX: number;
  containerLeft: number;
  containerWidth: number;
}

// Floats the tooltip near the cursor with edge-clamping so the panel
// never overflows the chart container. Width is fixed (240 px) so the
// content fits the 4-indicator breakdown comfortably on mobile.
function PostureTooltip({
  item,
  clientX,
  containerLeft,
  containerWidth,
}: PostureTooltipProps): JSX.Element {
  const TOOLTIP_WIDTH = 240;
  const cursorX = clientX - containerLeft;
  const margin = 8;
  // Flip the tooltip to the cursor's left when the right edge would
  // exceed the container so it doesn't get clipped.
  const left =
    cursorX + margin + TOOLTIP_WIDTH > containerWidth
      ? Math.max(0, cursorX - margin - TOOLTIP_WIDTH)
      : cursorX + margin;
  return (
    <div
      aria-hidden="true"
      className="pointer-events-none absolute top-2 z-10 rounded-md border border-slate-700 bg-slate-950/95 p-2 text-[11px] text-slate-100 shadow-lg backdrop-blur"
      style={{ left, width: TOOLTIP_WIDTH }}
    >
      <div className="mb-1 flex items-center gap-2">
        <span className="font-mono text-slate-300">{item.date}</span>
        <span
          className="rounded px-1.5 py-0.5 text-[10px] font-semibold"
          style={{
            backgroundColor: `${POSTURE_COLOR[item.posture]}33`,
            color: POSTURE_COLOR[item.posture],
          }}
        >
          {POSTURE_LABEL[item.posture]}
        </span>
        {typeof item.spy_close === 'number' && (
          <span className="font-mono text-slate-300">
            SPY ${item.spy_close.toFixed(2)}
          </span>
        )}
      </div>
      {(typeof item.spy_ma50 === 'number' || typeof item.spy_ma200 === 'number') && (
        <div className="mb-1 flex flex-wrap gap-x-2 gap-y-0.5 text-[10px] text-slate-400">
          {typeof item.spy_ma50 === 'number' && (
            <span className="flex items-center gap-1">
              <span
                aria-hidden="true"
                className="inline-block h-1.5 w-2.5 rounded-sm"
                style={{ backgroundColor: MA50_COLOR }}
              />
              50MA ${item.spy_ma50.toFixed(2)}
            </span>
          )}
          {typeof item.spy_ma200 === 'number' && (
            <span className="flex items-center gap-1">
              <span
                aria-hidden="true"
                className="inline-block h-1.5 w-2.5 rounded-sm"
                style={{ backgroundColor: MA200_COLOR }}
              />
              200MA ${item.spy_ma200.toFixed(2)}
            </span>
          )}
        </div>
      )}
      <div className="grid grid-cols-2 gap-x-2 gap-y-0.5">
        {REGIME_ORDER.map((name) => {
          const signal = item.regime_signals?.[name];
          const dot = signal ? SIGNAL_COLOR[signal] ?? '⚪' : '⚪';
          return (
            <div key={name} className="flex items-center gap-1">
              <span aria-hidden="true">{dot}</span>
              <span className="text-slate-300">{REGIME_LABEL[name] ?? name}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

interface StatRowProps {
  label: string;
  count: number;
  pct: number;
  color: string;
}

function StatRow({ label, count, pct, color }: StatRowProps): JSX.Element {
  return (
    <div className="flex items-center gap-1.5">
      <span
        aria-hidden="true"
        className="inline-block h-2.5 w-2.5 rounded-sm"
        style={{ backgroundColor: color }}
      />
      <dt className="text-slate-300">{label}</dt>
      <dd className="font-mono text-slate-400">
        {count} 日 ({pct}%)
      </dd>
    </div>
  );
}
