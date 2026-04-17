import { apiErrorEnvelopeSchema, type ApiErrorEnvelope } from '../lib/schemas';

// Typed exception surfaced by the fetch wrapper. Pages switch on `code` (stable
// machine identifier) and render `message` (user-facing Chinese). Structured
// payload lives in `details` so e.g. LoginPage can read attempts_remaining.
export class EisweinApiError extends Error {
  public readonly status: number;
  public readonly code: string;
  public readonly details: Readonly<Record<string, unknown>>;

  constructor(status: number, code: string, message: string, details?: Record<string, unknown>) {
    super(message);
    this.name = 'EisweinApiError';
    this.status = status;
    this.code = code;
    this.details = Object.freeze({ ...(details ?? {}) });
  }
}

// Thrown when a response body did not match the expected Zod schema. Distinct
// from EisweinApiError so callers can decide between "API returned an error
// envelope we understand" vs "API returned something completely unexpected".
export class SchemaValidationError extends Error {
  public readonly issues: readonly unknown[];

  constructor(message: string, issues: readonly unknown[]) {
    super(message);
    this.name = 'SchemaValidationError';
    this.issues = issues;
  }
}

// Network/unreachable-server failure (fetch itself rejected). Kept separate so
// callers can distinguish offline from 4xx/5xx responses.
export class NetworkError extends Error {
  constructor(message = '無法連線到伺服器，請檢查網路。') {
    super(message);
    this.name = 'NetworkError';
  }
}

export function parseErrorEnvelope(status: number, body: unknown): EisweinApiError {
  const parsed = apiErrorEnvelopeSchema.safeParse(body);
  if (parsed.success) {
    const envelope: ApiErrorEnvelope = parsed.data;
    return new EisweinApiError(
      status,
      envelope.error.code,
      envelope.error.message,
      envelope.error.details,
    );
  }
  return new EisweinApiError(status, 'unknown_error', `伺服器回應錯誤 (HTTP ${status})`);
}
