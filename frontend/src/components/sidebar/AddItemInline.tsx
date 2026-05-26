import { useState } from 'react';
import { useAddTicker } from '../../hooks/useWatchlist';
import { useCreateWatchlistGroup } from '../../hooks/useWatchlistGroups';
import { EisweinApiError } from '../../api/errors';

// Bottom of the sidebar. Starts collapsed as a single "+ 新增代碼 / 群組"
// button; on click expands into a form with a mode toggle (代碼 / 群組).
//
// Validation: ticker input is auto-uppercased + stripped of whitespace +
// validated against `^[A-Z0-9.\-]{1,10}$` per STAFF_REVIEW_DECISIONS I3.
// Group name caps at 32 chars to match the backend Pydantic schema.

const TICKER_REGEX = /^[A-Z0-9.-]{1,10}$/;

type Mode = 'ticker' | 'group';

export function AddItemInline(): JSX.Element {
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<Mode>('ticker');
  const [value, setValue] = useState('');
  const [error, setError] = useState<string | null>(null);
  const addTicker = useAddTicker();
  const createGroup = useCreateWatchlistGroup();

  const reset = (): void => {
    setValue('');
    setError(null);
  };

  const handleSubmit = async (
    event: React.FormEvent<HTMLFormElement>,
  ): Promise<void> => {
    event.preventDefault();
    setError(null);
    if (mode === 'ticker') {
      const normalized = value.trim().toUpperCase();
      if (!TICKER_REGEX.test(normalized)) {
        setError('代碼格式：1-10 字，僅限 A-Z 0-9 . -');
        return;
      }
      try {
        await addTicker.mutateAsync(normalized);
        reset();
      } catch (err) {
        setError(err instanceof EisweinApiError ? err.message : '新增失敗');
      }
    } else {
      const trimmed = value.trim();
      if (!trimmed || trimmed.length > 32) {
        setError('群組名稱：1-32 字元');
        return;
      }
      try {
        await createGroup.mutateAsync({ name: trimmed });
        reset();
      } catch (err) {
        setError(err instanceof EisweinApiError ? err.message : '新增失敗');
      }
    }
  };

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="w-full rounded-lg border border-dashed border-stone-300 px-3 py-2 text-sm text-stone-500 hover:border-stone-400 hover:bg-stone-50 hover:text-stone-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500"
      >
        + 新增代碼 / 群組
      </button>
    );
  }

  return (
    <form
      onSubmit={(e) => void handleSubmit(e)}
      className="flex flex-col gap-2 rounded-lg border border-stone-200 bg-white p-2"
    >
      <div role="radiogroup" aria-label="新增類型" className="flex gap-1">
        <button
          type="button"
          role="radio"
          aria-checked={mode === 'ticker'}
          onClick={() => {
            setMode('ticker');
            reset();
          }}
          className={`flex-1 rounded-md px-2 py-1 text-xs font-medium ${
            mode === 'ticker'
              ? 'bg-sky-600 text-white'
              : 'bg-stone-100 text-stone-600 hover:bg-stone-200'
          }`}
        >
          新增代碼
        </button>
        <button
          type="button"
          role="radio"
          aria-checked={mode === 'group'}
          onClick={() => {
            setMode('group');
            reset();
          }}
          className={`flex-1 rounded-md px-2 py-1 text-xs font-medium ${
            mode === 'group'
              ? 'bg-sky-600 text-white'
              : 'bg-stone-100 text-stone-600 hover:bg-stone-200'
          }`}
        >
          新增群組
        </button>
      </div>
      <input
        type="text"
        value={value}
        onChange={(e) =>
          setValue(mode === 'ticker' ? e.target.value.toUpperCase() : e.target.value)
        }
        placeholder={mode === 'ticker' ? '例：NVDA' : '例：AI 重點'}
        aria-label={mode === 'ticker' ? '股票代碼' : '群組名稱'}
        autoFocus
        className="rounded-md border border-stone-300 bg-white px-2 py-1 text-sm text-stone-900 placeholder:text-stone-400 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-500"
      />
      {error && (
        <p role="alert" className="text-xs text-rose-600">
          {error}
        </p>
      )}
      <div className="flex gap-1">
        <button
          type="submit"
          disabled={addTicker.isPending || createGroup.isPending}
          className="flex-1 rounded-md bg-sky-600 px-2 py-1 text-xs font-semibold text-white hover:bg-sky-500 disabled:opacity-60"
        >
          確認
        </button>
        <button
          type="button"
          onClick={() => {
            setOpen(false);
            reset();
          }}
          className="rounded-md border border-stone-300 px-2 py-1 text-xs text-stone-600 hover:bg-stone-100"
        >
          取消
        </button>
      </div>
    </form>
  );
}
