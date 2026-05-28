import type { EventType } from '../../api/calendar';

interface EventTypeFilterProps {
  selected: ReadonlySet<EventType>;
  onChange: (next: ReadonlySet<EventType>) => void;
}

const OPTIONS: ReadonlyArray<{ value: EventType; label: string; tintClass: string }> = [
  { value: 'earnings', label: '財報', tintClass: 'border-emerald-300 bg-emerald-50 text-emerald-700' },
  { value: 'macro', label: '總經', tintClass: 'border-sky-300 bg-sky-50 text-sky-700' },
  { value: 'industry', label: '產業', tintClass: 'border-violet-300 bg-violet-50 text-violet-700' },
];

// Type-aware chip row. Behaves like the sidebar's tag filter: empty
// selection = "all". Active selection = "only these types". Mutually
// inclusive (multi-select).
export function EventTypeFilter({ selected, onChange }: EventTypeFilterProps): JSX.Element {
  const allActive = selected.size === 0;
  const toggle = (value: EventType): void => {
    const next = new Set(selected);
    if (next.has(value)) next.delete(value);
    else next.add(value);
    onChange(next);
  };

  return (
    <div
      role="group"
      aria-label="事件類型篩選"
      data-testid="calendar-event-type-filter"
      className="flex flex-wrap items-center gap-1.5"
    >
      <button
        type="button"
        aria-pressed={allActive}
        onClick={() => onChange(new Set())}
        className={`rounded-full border px-2 py-0.5 text-xs font-medium transition ${
          allActive
            ? 'border-sky-300 bg-sky-50 text-sky-700'
            : 'border-stone-200 bg-white text-stone-500 hover:bg-stone-100'
        }`}
      >
        全部
      </button>
      {OPTIONS.map((opt) => {
        const active = selected.has(opt.value);
        return (
          <button
            key={opt.value}
            type="button"
            aria-pressed={active}
            onClick={() => toggle(opt.value)}
            className={`rounded-full border px-2 py-0.5 text-xs font-medium transition ${
              active ? opt.tintClass : 'border-stone-200 bg-white text-stone-500 hover:bg-stone-100'
            }`}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}
