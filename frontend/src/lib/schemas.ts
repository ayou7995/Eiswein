import { z } from 'zod';

// Standardized error envelope (STAFF_REVIEW_DECISIONS.md B6). Every backend
// error is serialized to this shape by the FastAPI global exception handler.
export const apiErrorEnvelopeSchema = z.object({
  error: z.object({
    code: z.string(),
    message: z.string(),
    details: z.record(z.unknown()).optional(),
  }),
});

export type ApiErrorEnvelope = z.infer<typeof apiErrorEnvelopeSchema>;

// Ticker symbol normalization (STAFF_REVIEW_DECISIONS.md I17). Same regex used
// in backend pydantic validator — allow uppercase letters/digits plus . and -
// so BRK.B and class-A tickers parse cleanly.
export const TICKER_SYMBOL_REGEX = /^[A-Z0-9.\-]{1,10}$/;

export const tickerSymbolSchema = z
  .string()
  .transform((raw) => raw.trim().toUpperCase())
  .refine((value) => TICKER_SYMBOL_REGEX.test(value), {
    message: '請輸入有效的股票代碼（英數字，最多 10 字）',
  });
