import { useMemo } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { LoadingSpinner } from './LoadingSpinner';

export type PositionFormMode = 'open' | 'add' | 'reduce';

const MODE_LABELS: Record<PositionFormMode, { title: string; submit: string }> = {
  open: { title: '開新持倉', submit: '建立持倉' },
  add: { title: '加碼', submit: '加碼' },
  reduce: { title: '減碼', submit: '減碼' },
};

// Positive-decimal strings only. Keeping as strings avoids float64 drift
// for high-precision share counts (fractional shares / large sizes).
const POSITIVE_DECIMAL_REGEX = /^\d+(\.\d+)?$/;

interface FormValues {
  symbol: string;
  shares: string;
  price: string;
  executedAt: string;
  note: string;
}

export type PositionFormValues = FormValues;

export interface PositionFormProps {
  mode: PositionFormMode;
  availableSymbols?: readonly string[];
  symbol?: string;
  maxShares?: string | null;
  onSubmit: (values: PositionFormValues) => Promise<void> | void;
  onCancel: () => void;
  submitError?: string | null;
  submitting?: boolean;
}

function buildSchema(mode: PositionFormMode, maxShares: string | null | undefined) {
  const sharesField = z
    .string()
    .min(1, '請輸入股數')
    .regex(POSITIVE_DECIMAL_REGEX, '請輸入正數')
    .superRefine((value, ctx) => {
      const n = Number.parseFloat(value);
      if (!Number.isFinite(n) || n <= 0) {
        ctx.addIssue({ code: z.ZodIssueCode.custom, message: '股數需大於 0' });
        return;
      }
      if (mode === 'reduce' && maxShares != null) {
        const cap = Number.parseFloat(maxShares);
        if (Number.isFinite(cap) && n > cap) {
          ctx.addIssue({
            code: z.ZodIssueCode.custom,
            message: `減碼股數不可超過 ${maxShares}`,
          });
        }
      }
    });

  const priceField = z
    .string()
    .min(1, '請輸入價格')
    .regex(POSITIVE_DECIMAL_REGEX, '請輸入正數')
    .refine((v) => {
      const n = Number.parseFloat(v);
      return Number.isFinite(n) && n > 0;
    }, '價格需大於 0');

  return z.object({
    symbol:
      mode === 'open'
        ? z.string().min(1, '請選擇股票代碼')
        : z.string().optional().default(''),
    shares: sharesField,
    price: priceField,
    executedAt: z.string().min(1, '請輸入日期時間'),
    note: z.string().max(500, '備註最多 500 字').optional().default(''),
  });
}

function nowIsoLocal(): string {
  const now = new Date();
  const offset = now.getTimezoneOffset();
  const local = new Date(now.getTime() - offset * 60_000);
  return local.toISOString().slice(0, 16);
}

export function PositionForm({
  mode,
  availableSymbols = [],
  symbol,
  maxShares,
  onSubmit,
  onCancel,
  submitError,
  submitting = false,
}: PositionFormProps): JSX.Element {
  const schema = useMemo(() => buildSchema(mode, maxShares ?? null), [mode, maxShares]);

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      symbol: symbol ?? '',
      shares: '',
      price: '',
      executedAt: nowIsoLocal(),
      note: '',
    },
  });

  const labels = MODE_LABELS[mode];

  return (
    <form
      noValidate
      onSubmit={handleSubmit((values) => onSubmit(values))}
      className="flex flex-col gap-4"
    >
      <div className="flex flex-col gap-1">
        <label htmlFor="position-symbol" className="text-sm font-medium text-slate-300">
          股票代碼
        </label>
        {mode === 'open' ? (
          <select
            id="position-symbol"
            aria-invalid={Boolean(errors.symbol)}
            aria-describedby={errors.symbol ? 'position-symbol-error' : undefined}
            {...register('symbol')}
            className="rounded-md border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
          >
            <option value="">請選擇…</option>
            {availableSymbols.map((sym) => (
              <option key={sym} value={sym}>
                {sym}
              </option>
            ))}
          </select>
        ) : (
          <input
            id="position-symbol"
            type="text"
            readOnly
            value={symbol ?? ''}
            className="rounded-md border border-slate-700 bg-slate-900 px-3 py-2 font-mono text-sm text-slate-200"
          />
        )}
        {errors.symbol && (
          <p id="position-symbol-error" role="alert" className="text-xs text-signal-red">
            {errors.symbol.message}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-1">
        <label htmlFor="position-shares" className="text-sm font-medium text-slate-300">
          股數{maxShares != null && mode === 'reduce' ? `（最多 ${maxShares}）` : ''}
        </label>
        <input
          id="position-shares"
          type="text"
          inputMode="decimal"
          autoComplete="off"
          aria-invalid={Boolean(errors.shares)}
          aria-describedby={errors.shares ? 'position-shares-error' : undefined}
          {...register('shares')}
          className="rounded-md border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
        />
        {errors.shares && (
          <p id="position-shares-error" role="alert" className="text-xs text-signal-red">
            {errors.shares.message}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-1">
        <label htmlFor="position-price" className="text-sm font-medium text-slate-300">
          單價
        </label>
        <input
          id="position-price"
          type="text"
          inputMode="decimal"
          autoComplete="off"
          aria-invalid={Boolean(errors.price)}
          aria-describedby={errors.price ? 'position-price-error' : undefined}
          {...register('price')}
          className="rounded-md border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
        />
        {errors.price && (
          <p id="position-price-error" role="alert" className="text-xs text-signal-red">
            {errors.price.message}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-1">
        <label htmlFor="position-executed-at" className="text-sm font-medium text-slate-300">
          執行時間
        </label>
        <input
          id="position-executed-at"
          type="datetime-local"
          aria-invalid={Boolean(errors.executedAt)}
          aria-describedby={errors.executedAt ? 'position-executed-at-error' : undefined}
          {...register('executedAt')}
          className="rounded-md border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
        />
        {errors.executedAt && (
          <p id="position-executed-at-error" role="alert" className="text-xs text-signal-red">
            {errors.executedAt.message}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-1">
        <label htmlFor="position-note" className="text-sm font-medium text-slate-300">
          備註（選填）
        </label>
        <textarea
          id="position-note"
          rows={2}
          maxLength={500}
          {...register('note')}
          className="rounded-md border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
        />
        {errors.note && (
          <p role="alert" className="text-xs text-signal-red">
            {errors.note.message}
          </p>
        )}
      </div>

      {submitError && (
        <div
          role="alert"
          className="rounded-md border border-signal-red/40 bg-signal-red/10 px-3 py-2 text-sm text-signal-red"
        >
          {submitError}
        </div>
      )}

      <div className="flex items-center justify-end gap-2">
        <button
          type="button"
          onClick={onCancel}
          className="rounded-md border border-slate-700 px-4 py-2 text-sm text-slate-200 hover:bg-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
        >
          取消
        </button>
        <button
          type="submit"
          disabled={submitting}
          className="inline-flex items-center gap-2 rounded-md bg-sky-600 px-4 py-2 text-sm font-semibold text-white hover:bg-sky-500 disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-300"
        >
          {submitting && <LoadingSpinner label={`${labels.submit}中…`} />}
          <span>{submitting ? `${labels.submit}中…` : labels.submit}</span>
        </button>
      </div>
    </form>
  );
}
