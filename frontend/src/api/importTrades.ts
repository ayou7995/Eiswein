import { z } from 'zod';
import { API_BASE_URL } from '../lib/constants';
import { ensureRefresh } from './client';
import {
  EisweinApiError,
  NetworkError,
  SchemaValidationError,
  parseErrorEnvelope,
} from './errors';

// Supported broker list — must match backend ``SUPPORTED_BROKERS`` in
// ``app/ingestion/importers/__init__.py``. The single :class:`BrokerCsvImporter`
// instance per key on the backend means adding a broker here requires a
// matching backend tuple entry. Order is the order the dropdown renders.
export const SUPPORTED_BROKERS = [
  { key: 'robinhood', label: 'Robinhood' },
  { key: 'moomoo', label: 'moomoo' },
  { key: 'schwab', label: 'Charles Schwab' },
  { key: 'fidelity', label: 'Fidelity' },
  { key: 'etrade', label: 'E*TRADE' },
  { key: 'tdameritrade', label: 'TD Ameritrade' },
  { key: 'chase', label: 'Chase (J.P. Morgan)' },
  { key: 'ibkr', label: 'Interactive Brokers' },
  { key: 'vanguard', label: 'Vanguard' },
  { key: 'webull', label: 'Webull' },
  { key: 'merrill', label: 'Merrill Edge' },
  { key: 'sofi', label: 'SoFi Active Invest' },
  { key: 'public', label: 'Public' },
  { key: 'other', label: 'Other' },
] as const;

export const brokerKeySchema = z.enum([
  'robinhood',
  'moomoo',
  'schwab',
  'fidelity',
  'etrade',
  'tdameritrade',
  'chase',
  'ibkr',
  'vanguard',
  'webull',
  'merrill',
  'sofi',
  'public',
  'other',
]);
export type BrokerKey = z.infer<typeof brokerKeySchema>;

export const importIssueSeveritySchema = z.enum(['warn', 'error']);
export type ImportIssueSeverity = z.infer<typeof importIssueSeveritySchema>;

export const importIssueSchema = z.object({
  row_index: z.number().int(),
  severity: importIssueSeveritySchema,
  code: z.string(),
  message: z.string(),
});
export type ImportIssue = z.infer<typeof importIssueSchema>;

export const tradeSideSchema = z.enum(['buy', 'sell']);

// Decimals arrive as strings to preserve precision (same wire contract as
// positions). Parse with parseDecimalString() only at display time.
export const tradeImportRecordSchema = z.object({
  symbol: z.string(),
  side: tradeSideSchema,
  shares: z.string(),
  price: z.string(),
  executed_at: z.string().datetime({ offset: true }),
  external_id: z.string(),
  source: z.string(),
  note: z.string().nullable(),
});
export type TradeImportRecord = z.infer<typeof tradeImportRecordSchema>;

export const previewActionSchema = z.enum([
  'import',
  'skip_duplicate',
  'warn',
  'error',
]);
export type PreviewAction = z.infer<typeof previewActionSchema>;

export const previewRowSchema = z.object({
  record: tradeImportRecordSchema,
  action: previewActionSchema,
  issues: z.array(importIssueSchema),
});
export type PreviewRow = z.infer<typeof previewRowSchema>;

export const importSummarySchema = z.object({
  would_import: z.number().int().nonnegative(),
  would_skip_duplicate: z.number().int().nonnegative(),
  warnings: z.number().int().nonnegative(),
  errors: z.number().int().nonnegative(),
  imported: z.number().int().nonnegative(),
  skipped_duplicate: z.number().int().nonnegative(),
});
export type ImportSummary = z.infer<typeof importSummarySchema>;

export const previewResponseSchema = z.object({
  broker: z.string(),
  total_rows: z.number().int().nonnegative(),
  parsed: z.array(previewRowSchema),
  file_issues: z.array(importIssueSchema),
  summary: importSummarySchema,
});
export type PreviewResponse = z.infer<typeof previewResponseSchema>;

export const applyResponseSchema = z.object({
  broker: z.string(),
  summary: importSummarySchema,
  issues: z.array(importIssueSchema),
});
export type ApplyResponse = z.infer<typeof applyResponseSchema>;

interface MultipartRequestOptions<TResponse> {
  path: string;
  broker: BrokerKey;
  file: File;
  schema: z.ZodSchema<TResponse>;
}

async function dispatchMultipart(
  path: string,
  broker: BrokerKey,
  file: File,
): Promise<{ status: number; body: unknown }> {
  // Build FormData on every dispatch. FormData is single-use because the
  // underlying ReadableStream is consumed once fetch sends it, so a retry
  // after 401-refresh must re-create the body.
  const form = new FormData();
  form.append('broker', broker);
  form.append('file', file);

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method: 'POST',
      credentials: 'include',
      headers: { Accept: 'application/json' },
      body: form,
    });
  } catch (cause) {
    throw new NetworkError(cause instanceof Error ? cause.message : undefined);
  }

  const contentType = response.headers.get('content-type') ?? '';
  let body: unknown = null;
  if (response.status !== 204 && contentType.includes('application/json')) {
    try {
      body = (await response.json()) as unknown;
    } catch {
      body = null;
    }
  }
  return { status: response.status, body };
}

async function multipartRequest<TResponse>({
  path,
  broker,
  file,
  schema,
}: MultipartRequestOptions<TResponse>): Promise<TResponse> {
  let result = await dispatchMultipart(path, broker, file);

  if (result.status === 401) {
    try {
      await ensureRefresh();
    } catch {
      throw parseErrorEnvelope(result.status, result.body);
    }
    result = await dispatchMultipart(path, broker, file);
  }

  if (result.status >= 400) {
    throw parseErrorEnvelope(result.status, result.body);
  }

  const parsed = schema.safeParse(result.body);
  if (!parsed.success) {
    throw new SchemaValidationError(
      `回應資料格式錯誤 (${path})`,
      parsed.error.issues,
    );
  }
  return parsed.data;
}

// Re-export so callers can pattern-match on rate_limited etc. without
// reaching into ./errors directly.
export { EisweinApiError };

export function previewTradeImport(
  broker: BrokerKey,
  file: File,
): Promise<PreviewResponse> {
  return multipartRequest({
    path: '/api/v1/import/trades/preview',
    broker,
    file,
    schema: previewResponseSchema,
  });
}

export function applyTradeImport(
  broker: BrokerKey,
  file: File,
): Promise<ApplyResponse> {
  return multipartRequest({
    path: '/api/v1/import/trades/apply',
    broker,
    file,
    schema: applyResponseSchema,
  });
}
