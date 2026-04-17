import { forwardRef, useCallback, type ChangeEvent, type InputHTMLAttributes } from 'react';
import { TICKER_SYMBOL_REGEX } from '../lib/schemas';

// Ticker input mirrors the backend pydantic validator (STAFF_REVIEW_DECISIONS.md
// I17): uppercase/digits/./- only, max 10 chars, auto-uppercase, no whitespace.
// The onChange contract gives the parent the cleaned value directly so forms
// never have to remember to normalise.
type NativeInputProps = Omit<
  InputHTMLAttributes<HTMLInputElement>,
  'onChange' | 'value' | 'type' | 'pattern' | 'maxLength'
>;

export interface TickerInputProps extends NativeInputProps {
  value: string;
  onChange: (cleanedValue: string) => void;
}

const TICKER_PATTERN_STR = '^[A-Z0-9.\\-]{1,10}$';

export const TickerInput = forwardRef<HTMLInputElement, TickerInputProps>(
  function TickerInput({ value, onChange, className = '', ...rest }, ref) {
    const handleChange = useCallback(
      (event: ChangeEvent<HTMLInputElement>) => {
        const cleaned = event.target.value.replace(/\s+/g, '').toUpperCase();
        onChange(cleaned);
      },
      [onChange],
    );

    const isValid = value === '' || TICKER_SYMBOL_REGEX.test(value);

    return (
      <input
        ref={ref}
        {...rest}
        type="text"
        inputMode="text"
        autoCapitalize="characters"
        autoCorrect="off"
        autoComplete="off"
        spellCheck={false}
        maxLength={10}
        pattern={TICKER_PATTERN_STR}
        value={value}
        onChange={handleChange}
        aria-invalid={!isValid}
        className={`rounded-md border bg-slate-800 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-400 ${
          isValid ? 'border-slate-600' : 'border-signal-red'
        } ${className}`}
      />
    );
  },
);
