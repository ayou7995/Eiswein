import { useCallback, useEffect, useRef } from 'react';
import type { CalendarEvent } from '../../api/calendar';
import {
  daysSinceVerified,
  extractIndustryPayload,
  type IndustryPayload,
} from '../../api/calendar';

interface EventDrawerProps {
  date: Date;
  events: readonly CalendarEvent[];
  isPast: boolean;
  onClose: () => void;
  onNavigateDay: (offset: number) => void;
  // Days since last_verified_at after which the drawer shows a
  // "資料可能過時" banner. Threshold ships from backend Settings.
  staleThresholdDays?: number;
}

const TYPE_COLOR: Record<CalendarEvent['type'], string> = {
  earnings: 'bg-emerald-500',
  macro: 'bg-sky-500',
  industry: 'bg-violet-500',
};

const TYPE_LABEL: Record<CalendarEvent['type'], string> = {
  earnings: '財報',
  macro: '總經',
  industry: '產業',
};

// Right-side fixed drawer holding the full day's event detail. Closes
// on ESC, backdrop click, and the explicit close button. Up/down day
// navigation lets the operator scan a week without dismissing the
// drawer — primary use case is "what's the next few days look like?".
export function EventDrawer({
  date,
  events,
  isPast,
  onClose,
  onNavigateDay,
  staleThresholdDays = 21,
}: EventDrawerProps): JSX.Element {
  const panelRef = useRef<HTMLDivElement | null>(null);
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);
  const handleClose = useCallback(() => onClose(), [onClose]);

  useEffect(() => {
    closeButtonRef.current?.focus();
    const original = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') {
        event.preventDefault();
        handleClose();
      } else if (event.key === 'ArrowRight') {
        event.preventDefault();
        onNavigateDay(1);
      } else if (event.key === 'ArrowLeft') {
        event.preventDefault();
        onNavigateDay(-1);
      }
    };
    document.addEventListener('keydown', onKey);
    return () => {
      document.body.style.overflow = original;
      document.removeEventListener('keydown', onKey);
    };
  }, [handleClose, onNavigateDay]);

  const formatted = `${date.getFullYear()}/${date.getMonth() + 1}/${date.getDate()}`;
  return (
    <div
      data-testid="calendar-event-drawer-backdrop"
      role="presentation"
      onClick={handleClose}
      className="fixed inset-0 z-40 bg-black/30"
    >
      <aside
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={`${formatted} 事件詳情`}
        data-testid="calendar-event-drawer"
        onClick={(e) => e.stopPropagation()}
        className="absolute inset-y-0 right-0 flex w-[400px] max-w-[90vw] flex-col bg-white shadow-xl"
      >
        <header className="flex items-center justify-between border-b border-stone-200 px-4 py-3">
          <div className="flex flex-col">
            <span className="text-sm font-semibold text-stone-900">{formatted}</span>
            <span className="text-xs text-stone-500">
              {events.length === 0 ? '今日無事件' : `共 ${events.length} 件`}
            </span>
          </div>
          <button
            ref={closeButtonRef}
            type="button"
            aria-label="關閉"
            onClick={handleClose}
            className="rounded-md px-2 py-1 text-stone-500 hover:bg-stone-100 hover:text-stone-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500"
          >
            <span aria-hidden="true">✕</span>
          </button>
        </header>

        <div className="flex-1 overflow-y-auto px-4 py-3">
          {events.length === 0 ? (
            <p className="text-sm text-stone-500">這天沒有任何催化劑事件。</p>
          ) : (
            <ul role="list" className="flex flex-col gap-3">
              {events.map((evt) => (
                <li
                  key={evt.id}
                  data-testid={`calendar-event-detail-${evt.id}`}
                  className={`rounded-md border border-stone-200 p-3 ${
                    isPast ? 'bg-stone-50 text-stone-500' : 'bg-white text-stone-800'
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <span
                      aria-hidden="true"
                      className={`inline-block h-2 w-2 shrink-0 rounded-full ${TYPE_COLOR[evt.type]}`}
                    />
                    <span className="text-xs font-medium uppercase tracking-wide text-stone-500">
                      {TYPE_LABEL[evt.type]}
                    </span>
                    {evt.tickerSymbol && (
                      <span className="font-mono text-xs text-stone-700">
                        {evt.tickerSymbol}
                      </span>
                    )}
                    {evt.eventTime && (
                      <span className="ml-auto text-xs text-stone-500">{evt.eventTime}</span>
                    )}
                  </div>
                  <div className="mt-1 text-sm font-semibold">{evt.title}</div>
                  <PayloadLines payload={evt.payload} />
                  {evt.type === 'industry' && (
                    <IndustryTrustLines
                      event={evt}
                      staleThresholdDays={staleThresholdDays}
                    />
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>

        <footer className="flex items-center justify-between border-t border-stone-200 px-4 py-2 text-xs">
          <button
            type="button"
            onClick={() => onNavigateDay(-1)}
            className="rounded-md px-2 py-1 text-stone-600 hover:bg-stone-100"
          >
            ← 前一日
          </button>
          <span className="text-stone-400" aria-hidden="true">
            ← →
          </span>
          <button
            type="button"
            onClick={() => onNavigateDay(1)}
            className="rounded-md px-2 py-1 text-stone-600 hover:bg-stone-100"
          >
            次日 →
          </button>
        </footer>
      </aside>
    </div>
  );
}

function PayloadLines({ payload }: { payload: Record<string, unknown> | null }): JSX.Element | null {
  if (!payload) return null;
  const lines: string[] = [];
  if (typeof payload['consensus_eps'] === 'number') {
    lines.push(`共識 EPS: $${payload['consensus_eps'].toFixed(2)}`);
  }
  if (typeof payload['time_marker'] === 'string') {
    lines.push(`時間: ${payload['time_marker']}`);
  }
  if (typeof payload['note'] === 'string') {
    lines.push(payload['note']);
  }
  const tags = payload['tags'];
  if (Array.isArray(tags) && tags.length > 0) {
    lines.push(`標籤: ${tags.join(', ')}`);
  }
  if (lines.length === 0) return null;
  return (
    <ul className="mt-2 flex flex-col gap-0.5 text-xs">
      {lines.map((line) => (
        <li key={line} className="text-stone-500">
          {line}
        </li>
      ))}
    </ul>
  );
}

const CONFIDENCE_BADGE: Record<
  'confirmed' | 'estimated' | 'uncertain',
  { label: string; cls: string }
> = {
  confirmed: {
    label: '✓ 已確認',
    cls: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  },
  estimated: {
    label: '〜 估計',
    cls: 'bg-amber-50 text-amber-700 border-amber-200',
  },
  uncertain: {
    label: '? 不確定',
    cls: 'bg-rose-50 text-rose-700 border-rose-200',
  },
};

// Renders confidence badge + source URL + verified-ago + notes for
// Gemini-sourced industry events. Yaml-sourced rows (no payload metadata)
// render nothing — graceful degradation.
function IndustryTrustLines({
  event,
  staleThresholdDays,
}: {
  event: CalendarEvent;
  staleThresholdDays: number;
}): JSX.Element | null {
  const trust = extractIndustryPayload(event.payload);
  if (
    trust.confidence === null &&
    trust.sourceUrl === null &&
    trust.lastVerifiedAt === null &&
    trust.notes === null
  ) {
    return null;
  }
  const days = daysSinceVerified(trust);
  const stale = days !== null && days >= staleThresholdDays;
  return (
    <div
      data-testid="calendar-industry-trust"
      data-stale={stale || undefined}
      className="mt-3 flex flex-col gap-1 text-xs"
    >
      {trust.confidence && (
        <span
          data-testid="calendar-industry-confidence"
          data-confidence={trust.confidence}
          className={`inline-flex w-fit items-center rounded-md border px-1.5 py-0.5 ${CONFIDENCE_BADGE[trust.confidence].cls}`}
        >
          {CONFIDENCE_BADGE[trust.confidence].label}
        </span>
      )}
      <SourceLine source={trust.sourceUrl} />
      <VerifiedLine days={days} stale={stale} />
      {trust.notes && <p className="text-stone-500">{trust.notes}</p>}
      {stale && days !== null && (
        <div
          role="status"
          data-testid="calendar-industry-stale-banner"
          className="mt-1 rounded-md border border-amber-300 bg-amber-50 px-2 py-1 text-amber-900"
        >
          ⚠ 這筆資料已 {days} 天未驗證,建議直接到官網確認。
        </div>
      )}
    </div>
  );
}

function SourceLine({ source }: { source: string | null }): JSX.Element | null {
  if (!source) return null;
  return (
    <a
      href={source}
      target="_blank"
      rel="noopener noreferrer"
      className="w-fit truncate text-sky-600 underline hover:text-sky-800"
    >
      來源 → {source}
    </a>
  );
}

function VerifiedLine({
  days,
  stale,
}: {
  days: number | null;
  stale: boolean;
}): JSX.Element | null {
  if (days === null) return null;
  return (
    <span className={stale ? 'text-amber-700' : 'text-stone-500'}>
      {days === 0 ? '今日驗證' : `${days} 天前驗證`}
    </span>
  );
}

// IndustryPayload is re-exported here so future callers can reuse it
// without bouncing through ``../../api/calendar``.
export type { IndustryPayload };
