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
  const range = Math.max(max - min, 1);
  const clampedValue = Math.max(min, Math.min(max, value));
  const markerLeftPct = ((clampedValue - min) / range) * 100;

  // Build segment widths from cumulative thresholds. The final segment
  // takes whatever fraction is left over to reach 100%.
  let cursor = min;
  const segments = zones.map((zone, idx) => {
    const upper = idx === zones.length - 1 ? max : zone.upTo;
    const width = ((upper - cursor) / range) * 100;
    const isCurrent =
      value >= cursor &&
      (idx === zones.length - 1 ? value <= upper : value < upper);
    cursor = upper;
    return { ...zone, width, isCurrent };
  });

  return (
    <div className="flex flex-col gap-1.5">
      <div
        role="img"
        aria-label={ariaLabel}
        className="relative h-3 w-full overflow-hidden rounded-md border border-slate-700/60"
      >
        <div className="flex h-full w-full">
          {segments.map((seg, idx) => (
            <div
              key={`${seg.label}-${idx}`}
              style={{ width: `${seg.width}%` }}
              className={seg.bg}
            />
          ))}
        </div>
        <div
          aria-hidden="true"
          style={{ left: `${markerLeftPct}%` }}
          className="absolute top-0 h-3 w-0.5 -translate-x-1/2 bg-slate-100 shadow-[0_0_0_1px_rgba(15,23,42,0.6)]"
        />
      </div>
      {/* Zone labels share the bar's width so each one sits below its
          segment. Proportional-width divs avoid manual percentage math. */}
      <div aria-hidden="true" className="flex w-full text-[11px]">
        {segments.map((seg, idx) => (
          <div
            key={`label-${seg.label}-${idx}`}
            style={{ width: `${seg.width}%` }}
            className={`px-0.5 text-center ${
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
