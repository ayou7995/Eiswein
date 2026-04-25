# Schwab Accounts and Trading API — Reference

**Source**: Schwab Developer Portal → Trader API - Individual → Accounts and Trading Production (Swagger)
**Captured**: 2026-04-21
**Status**: **three Account endpoints fully documented** (`/accounts/accountNumbers`, `/accounts`, `/accounts/{accountNumber}`). Sibling endpoints live in `orders.md`, `transactions.md`, `userpreference.md`.

Base URL: `https://api.schwabapi.com/trader/v1`

All endpoints require `Authorization: Bearer <access_token>` (see `oauth.md`).

### Common response headers
- `Schwab-Client-CorrelId` (string) — auto-generated correlation ID. **Capture this on every response** and include in error logs / support tickets.

### Common error envelope
All 4xx/5xx responses share this shape:
```json
{
  "message": "string",
  "errors": ["string"]
}
```
with `Schwab-Client-CorrelId` in headers.

Status codes returned by all three account endpoints:
- `200` — success
- `400` — validation error (bad request)
- `401` — auth token invalid OR caller has no linked accounts
- `403` — forbidden (scope/role issue)
- `404` — resource not found
- `500` — unexpected server error
- `503` — temporary server problem

---

## CRITICAL — Account Hash Value

**Schwab does NOT accept your raw Schwab account number in Trader API URLs.** You MUST first exchange it for an opaque `hashValue` and use that everywhere.

Schwab's own docs on `/accounts/{accountNumber}` describe the path param as "The **encrypted ID** of the account" — confirming the hash-value requirement.

### `GET /accounts/accountNumbers`

> "Account numbers in plain text cannot be used outside of headers or request/response bodies. As the first step consumers must invoke this service to retrieve the list of plain text/encrypted value pairs, and use encrypted account values for all subsequent calls for any accountNumber request."

**Request**:
```
GET /trader/v1/accounts/accountNumbers
Authorization: Bearer <access_token>
```

No parameters. No request body.

**Response** `200 application/json`:
```json
[
  {
    "accountNumber": "string",
    "hashValue": "string"
  }
]
```

**Eiswein usage**:
- Call **once on OAuth completion**.
- Persist `(account_number, hash_value)` on the `BrokerCredential` table (both fields encrypted at rest with AES-256-GCM — account number is PII).
- Every subsequent Trader API call uses the `hashValue` in the `{accountNumber}` path param.
- If a call returns 404 on a known hash, re-fetch this mapping (account may have been renumbered).

---

## `GET /accounts`

**Purpose**: "Get linked account(s) balances and positions for the logged-in user."

### Query Parameters

| Name | Type | Required | Values | Notes |
|---|---|---|---|---|
| `fields` | string (query) | no | `positions` | Opt-in for position array. Without this, only balances are returned. Example: `?fields=positions`. |

### Response `200 application/json`

Returns an **array** of `{ "securitiesAccount": { ... } }` objects. One per linked account.

Key fields within `securitiesAccount`:
- `accountNumber` (string) — the plaintext account number
- `roundTrips` (int), `isDayTrader` (bool), `isClosingOnlyRestricted` (bool), `pfcbFlag` (bool)
- `positions` (array) — present only when `?fields=positions`
- `initialBalances`, `currentBalances`, `projectedBalances` (three snapshot objects, always present)

### Position object (fields that matter for Eiswein)

| Field | Type | Eiswein use |
|---|---|---|
| `instrument.symbol` | string | Match against our `Position.symbol` |
| `instrument.cusip` | string | Cross-reference identifier |
| `instrument.description` | string | Human name for UI |
| `instrument.type` | string | enum includes `SWEEP_VEHICLE`, more values TBD |
| `longQuantity` | number | Shares held long |
| `shortQuantity` | number | Shares held short |
| `averagePrice` | number | Cost basis |
| `averageLongPrice`, `averageShortPrice` | number | Leg-specific cost bases |
| `taxLotAverageLongPrice`, `taxLotAverageShortPrice` | number | Tax-lot basis |
| `marketValue` | number | Current market value |
| `longOpenProfitLoss`, `shortOpenProfitLoss` | number | Unrealized P&L |
| `currentDayProfitLoss`, `currentDayProfitLossPercentage` | number | Daily P&L |
| `currentDayCost` | number | Today's cost basis |
| `settledLongQuantity`, `settledShortQuantity` | number | Settled shares |
| `agedQuantity` | number | Aged (T+2 settled) shares |
| `previousSessionLongQuantity`, `previousSessionShortQuantity` | number | Prior session holdings |
| `maintenanceRequirement` | number | Margin requirement |

### Balance objects

Three sets are returned per account:

- **`initialBalances`** — start-of-day snapshot. Includes `cashBalance`, `cashAvailableForTrading`, `liquidationValue`, `accountValue`, `longStockValue`, `shortStockValue`, `longOptionMarketValue`, `shortOptionMarketValue`, `accruedInterest`, `buyingPower`, `dayTradingBuyingPower`, margin fields, `mutualFundValue`, `bondValue`, `moneyMarketFund`, `unsettledCash`, `pendingDeposits`, etc.
- **`currentBalances`** — realtime live values. Includes `availableFunds`, `buyingPower`, `stockBuyingPower`, `optionBuyingPower`, `equity`, `equityPercentage`, `marginBalance`, `shortBalance`, `sma`, call fields, `isInCall`, etc.
- **`projectedBalances`** — same fields as `currentBalances` but projected forward (accounts for pending settlement).

**Eiswein usage** (Phase S2 account sync):
- Call daily with `?fields=positions`.
- Persist `currentBalances.liquidationValue` or `accountValue` for the "total portfolio value" card on Dashboard.
- Use `currentBalances.cashAvailableForTrading` for "可用現金" display.
- Reconcile `positions[]` against our internal `Position` table — flag drift (positions user added outside Eiswein).

---

## `GET /accounts/{accountNumber}`

**Purpose**: "Get a specific account balance and positions for the logged-in user."

### Path Parameters

| Name | Type | Required | Notes |
|---|---|---|---|
| `accountNumber` | string (path) | **yes** | **"The encrypted ID of the account"** — i.e. the `hashValue` from `/accounts/accountNumbers`, NOT the plaintext account number. |

### Query Parameters

Same as `/accounts`:

| Name | Type | Required | Values |
|---|---|---|---|
| `fields` | string (query) | no | `positions` |

### Response `200 application/json`

**Same object shape** as each array element in `/accounts` — a single `{"securitiesAccount": {...}}` (not wrapped in an array).

### Eiswein usage
- For a single-account portfolio: calling `/accounts` and pulling the first element is equivalent. We default to `/accounts` for simplicity.
- If we ever add multi-account UX (per-account page), use this endpoint with the specific hash.

---

## Related endpoints (documented in sibling files)

- **Orders** (7 endpoints: list, place, get, replace, cancel, cross-account list, preview): `orders.md`. Eiswein policy: read-only `GET` for reconciliation; never POST/PUT/DELETE.
- **Transactions** (2 endpoints: list, get-one): `transactions.md`. Used for Phase S2 trade-history backfill.
- **UserPreference** (1 endpoint): `userpreference.md`. **Mandatory prerequisite for Streamer WebSocket.**
