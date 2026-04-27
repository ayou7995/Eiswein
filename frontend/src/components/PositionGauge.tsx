// Generic 1-D position gauge: a horizontal bar split into colored zones,
// with a marker pinned at the current value.
//
// Reusable across indicators where "where am I on a continuous scale" is
// the primary insight — VIX (level), RSI (0-100), etc.
//
// Zones are passed in ascending order; the first zone covers `min..z[0].upTo`,
// the next covers `z[0].upTo..z[1].upTo`, and so on. The final zone implicitly
// extends to `max`. Each zone supplies its own color so callers can decide
// the semantics (e.g. for VIX both end zones are yellow, middle is green).
//
// The numeric value display is intentionally NOT rendered here — consumers
// inline it into their section header (next to other secondary stats) so
// the gauge stays focused on the visual band + zone labels.

export interface PositionGaugeZone {
  upTo: number;
  label: string;
  // Tailwind background color class for the zone segment + matching text
  // class for the zone label, kept as a pair so the consumer doesn't have
  // to think about light/dark or alpha values.
  bg: string;
  text: string;
}

export interface PositionGaugeProps {
  value: number;
  min: number;
  max: number;
  zones: ReadonlyArray<PositionGaugeZone>;
  ariaLabel: string;
  // Whether to mark the current zone label with a bold/coloured style.
  // Useful when the gauge is the only visual representation; superfluous
  // when the headline already names the zone.
  highlightCurrentZone?: boolean;
}

export function PositionGauge({
  value,
  min,
  max,
  zones,
  ariaLabel,
  highlightCurrentZone = false,
}: PositionGaugeProps): JSX.Element {
  // Guard against degenerate `max === min` only — never clamp to a
  // minimum (the previous `Math.max(max - min, 1)` silently broke any
  // gauge whose span was < 1, e.g. the relative-strength ±10 % range
  // where 0.2 was forced up to 1, compressing the red/amber zones to
  // 1/5 of their intended width).
  const range = max === min ? 1 : max - min;
  const clampedValue = Math.max(min, Math.min(max, value));
  const markerLeftPct = ((clampedValue - min) / range) * 100;
  // Track when the actual value blew past the gauge bounds so the
  // marker doesn't silently disappear at the edge under overflow-hidden.
  // The chevron + tinted edge band gives the user an unambiguous "out of
  // gauge" cue while the precise number still lives in the section header.
  const overflowAbove = value > max;
  const overflowBelow = value < min;

  // Build segment offsets + widths from cumulative thresholds. The final
  // segment is pinned to 100% (right edge) regardless of floating-point
  // accumulation so the bar always reaches the rightmost pixel.
  let cursor = min;
  const segments = zones.map((zone, idx) => {
    const isLast = idx === zones.length - 1;
    const upper = isLast ? max : zone.upTo;
    const leftPct = ((cursor - min) / range) * 100;
    const rightPct = isLast ? 100 : ((upper - min) / range) * 100;
    const width = rightPct - leftPct;
    const isCurrent =
      value >= cursor && (isLast ? value <= upper : value < upper);
    cursor = upper;
    return { ...zone, leftPct, width, isCurrent };
  });

  return (
    <div className="flex flex-col gap-1.5">
      <div
        role="img"
        aria-label={ariaLabel}
        className={`relative h-3 w-full overflow-hidden rounded-md border ${
          overflowAbove || overflowBelow
            ? 'border-amber-400/80 ring-1 ring-amber-400/30'
            : 'border-slate-700/60'
        }`}
      >
        {segments.map((seg, idx) => (
          <div
            key={`${seg.label}-${idx}`}
            style={{ left: `${seg.leftPct}%`, width: `${seg.width}%` }}
            className={`absolute top-0 h-full ${seg.bg}`}
          />
        ))}
        {overflowAbove ? (
          // Marker swaps from a thin tick to an edge-pinned chevron so
          // the user sees a discrete "blew past the scale" symbol rather
          // than a near-invisible 1px line clipped by overflow-hidden.
          <div
            aria-hidden="true"
            className="absolute right-0 top-0 flex h-3 items-center pr-0.5 text-[11px] font-bold leading-none text-amber-300 drop-shadow-[0_0_2px_rgba(0,0,0,0.6)]"
          >
            ▶
          </div>
        ) : overflowBelow ? (
          <div
            aria-hidden="true"
            className="absolute left-0 top-0 flex h-3 items-center pl-0.5 text-[11px] font-bold leading-none text-amber-300 drop-shadow-[0_0_2px_rgba(0,0,0,0.6)]"
          >
            ◀
          </div>
        ) : (
          <div
            aria-hidden="true"
            style={{ left: `${markerLeftPct}%` }}
            className="absolute top-0 h-3 w-0.5 -translate-x-1/2 bg-slate-100 shadow-[0_0_0_1px_rgba(15,23,42,0.6)]"
          />
        )}
      </div>
      {/* Labels mirror the bar's segment offsets so each sits centered
          beneath its zone. Absolute positioning matches the bar so any
          rounding stays consistent across the two layers. */}
      <div aria-hidden="true" className="relative h-4 w-full text-[11px]">
        {segments.map((seg, idx) => (
          <div
            key={`label-${seg.label}-${idx}`}
            style={{ left: `${seg.leftPct}%`, width: `${seg.width}%` }}
            className={`absolute top-0 px-0.5 text-center ${
              highlightCurrentZone && seg.isCurrent
                ? `font-semibold ${seg.text}`
                : seg.text
            }`}
          >
            {seg.label}
          </div>
        ))}
      </div>
    </div>
  );
}
