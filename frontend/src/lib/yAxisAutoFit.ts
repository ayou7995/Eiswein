// Percentile-based Y-axis bounds for indicator charts.
//
// Indicator charts have two scales they need to respect:
//
// 1. **Semantic bounds** — RSI must stay 0-100, ATR must stay ≥ 0,
//    VIX must stay ≥ 0. These are hard floors / ceilings from the
//    indicator's math.
// 2. **Visible data range** — within the selected time window the actual
//    values may only occupy a fraction of the semantic range. Showing
//    0-100 for an RSI that's been in 40-60 the whole month wastes 60% of
//    the vertical pixel budget.
//
// ``computeYBounds`` reconciles them by taking the 2nd / 98th percentile
// of the displayed series (robust to a single outlier bar from
// earnings / FOMC), padding by 5% of the data range, then clamping to
// the soft floor / ceiling. The result fills the chart usefully without
// ever going outside the indicator's natural scale.
//
// Why percentile and not min/max:
// * A single freak bar (e.g. VIX 82 on a flash crash inside a 5Y window)
//   would balloon the upper bound to 82, compressing the other 1259 bars
//   into the bottom 30% of pixels. Percentile clipping treats the spike
//   as an annotation, not the scale anchor.

export interface YBoundsOptions {
  // The lowest the bottom of the chart is allowed to go. RSI / ATR
  // pass 0; for unbounded indicators omit and the percentile picks.
  readonly softMin?: number;
  // Upper analogue. Pass 100 for RSI; omit for everything else.
  readonly softMax?: number;
  // Fraction of the data range to pad below / above the percentile
  // bounds. 0.05 = 5% on each side. Default 0.05.
  readonly padding?: number;
  // Lower / upper percentiles. Defaults to 0.02 / 0.98.
  readonly lowerQuantile?: number;
  readonly upperQuantile?: number;
}

export interface YBounds {
  readonly yMin: number;
  readonly yMax: number;
}

const DEFAULT_PADDING = 0.05;
const DEFAULT_LOWER_Q = 0.02;
const DEFAULT_UPPER_Q = 0.98;

// Pull the numeric value of ``key`` from a row, treating null / NaN /
// strings as missing.
function readNumber(row: Record<string, unknown>, key: string): number | null {
  const v = row[key];
  return typeof v === 'number' && Number.isFinite(v) ? v : null;
}

function quantile(sorted: ReadonlyArray<number>, q: number): number {
  // Linear-interpolation quantile (numpy-style). ``sorted`` MUST be
  // pre-sorted ascending and non-empty; callers guarantee both.
  const idx = q * (sorted.length - 1);
  const lo = Math.floor(idx);
  const hi = Math.ceil(idx);
  if (lo === hi) return sorted[lo]!;
  const t = idx - lo;
  return sorted[lo]! * (1 - t) + sorted[hi]! * t;
}

export function computeYBounds<T extends Record<string, unknown>>(
  series: ReadonlyArray<T>,
  keys: ReadonlyArray<string>,
  options: YBoundsOptions = {},
): YBounds {
  const values: number[] = [];
  for (const row of series) {
    for (const key of keys) {
      const v = readNumber(row, key);
      if (v !== null) values.push(v);
    }
  }
  const {
    softMin,
    softMax,
    padding = DEFAULT_PADDING,
    lowerQuantile = DEFAULT_LOWER_Q,
    upperQuantile = DEFAULT_UPPER_Q,
  } = options;

  // Degenerate cases: empty series falls back to the soft bounds. If a
  // soft bound is missing too we pick a small default scale (0 / 1)
  // rather than NaN — the chart should never crash on empty data.
  if (values.length === 0) {
    return {
      yMin: softMin ?? 0,
      yMax: softMax ?? 1,
    };
  }

  values.sort((a, b) => a - b);
  const lo = quantile(values, lowerQuantile);
  const hi = quantile(values, upperQuantile);
  // Use the FULL data range for the padding budget, not the percentile
  // span — otherwise tight series (variance ≈ 0) padding would itself
  // be ≈ 0 and the chart line would sit on the axis edge.
  const fullRange = values[values.length - 1]! - values[0]!;
  const pad = (fullRange === 0 ? Math.max(Math.abs(lo), 1) : fullRange) * padding;

  let yMin = lo - pad;
  let yMax = hi + pad;

  if (softMin !== undefined) yMin = Math.max(softMin, yMin);
  if (softMax !== undefined) yMax = Math.min(softMax, yMax);

  // Guarantee a non-zero span so the chart doesn't collapse into a line.
  if (yMax <= yMin) {
    const eps = Math.max(Math.abs(yMin) * 0.01, 0.001);
    yMax = yMin + eps;
  }

  return { yMin, yMax };
}
