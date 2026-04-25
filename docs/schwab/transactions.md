# Schwab Transactions API — Reference

**Source**: Schwab Developer Portal → Trader API - Individual → Accounts and Trading Production (Swagger)
**Captured**: 2026-04-21
**Status**: 2 endpoints fully documented.

Base URL: `https://api.schwabapi.com/trader/v1`

All endpoints require `Authorization: Bearer <access_token>`. Path `{accountNumber}` is the encrypted **hashValue** from `/accounts/accountNumbers` — see `accounts.md` §CRITICAL.

**Common response header**: `Schwab-Client-CorrelId` (auto-generated).
**Common error envelope / status codes**: see `accounts.md`. Both endpoints return 200/400/401/403/404/500/503.

---

## Canonical Transaction Object

Both endpoints return objects with this shape (the list endpoint wraps it in an array):

```json
{
  "activityId": 0,
  "time": "2026-04-21T22:08:23.236Z",
  "user": {
    "cdDomainId": "string",
    "login": "string",
    "type": "ADVISOR_USER",
    "userId": 0,
    "systemUserName": "string",
    "firstName": "string",
    "lastName": "string",
    "brokerRepCode": "string"
  },
  "description": "string",
  "accountNumber": "string",
  "type": "TRADE",
  "status": "VALID",
  "subAccount": "CASH",
  "tradeDate": "2026-04-21T22:08:23.236Z",
  "settlementDate": "2026-04-21T22:08:23.236Z",
  "positionId": 0,
  "orderId": 0,
  "netAmount": 0,
  "activityType": "ACTIVITY_CORRECTION",
  "transferItems": [
    {
      "instrument": {
        "cusip": "string",
        "symbol": "string",
        "description": "string",
        "instrumentId": 0,
        "netChange": 0,
        "type": "SWEEP_VEHICLE"
      },
      "amount": 0,
      "cost": 0,
      "price": 0,
      "feeType": "COMMISSION",
      "positionEffect": "OPENING"
    }
  ]
}
```

### Field tables

**Identity / linkage**
| Field | Type | Note |
|---|---|---|
| `activityId` | int64 | Unique per event. Use as idempotency key when importing. |
| `time` | ISO-8601 | When Schwab recorded the activity. |
| `accountNumber` | string | Plaintext (in body, not URL). |
| `orderId` | int64 | Links to an order (`orders.md`). 0 for non-order activity (dividends, transfers). |
| `positionId` | int64 | Links to a position row. |

**Classification**
| Field | Type | Values / note |
|---|---|---|
| `type` | enum | `TRADE`, `RECEIVE_AND_DELIVER`, `DIVIDEND_OR_INTEREST`, `ACH_RECEIPT`, `ACH_DISBURSEMENT`, `CASH_RECEIPT`, `CASH_DISBURSEMENT`, `ELECTRONIC_FUND`, `WIRE_OUT`, `WIRE_IN`, `JOURNAL`, `MEMORANDUM`, `MARGIN_CALL`, `MONEY_MARKET`, `SMA_ADJUSTMENT` |
| `status` | enum | `VALID`, `PENDING`, `INVALID` (inferred — only `VALID` seen). |
| `activityType` | enum | `ACTIVITY_CORRECTION` seen; full set undocumented. |
| `subAccount` | enum | `CASH`, `MARGIN`, `SHORT`, `DIV`, `INCOME` (inferred). |
| `description` | string | Free-form human description. |
| `netAmount` | decimal | Signed cash delta (negative = debit). |

**Settlement**
| Field | Type | Note |
|---|---|---|
| `tradeDate` | ISO-8601 | When the trade was executed. |
| `settlementDate` | ISO-8601 | T+1 or T+2 depending on asset. |

**User (who initiated)**
- `user.userId`, `user.login`, `user.type` (`ADVISOR_USER`, `CLIENT_USER`, `BROKER_USER`, `SYSTEM_USER`), `user.{firstName, lastName}`, `user.brokerRepCode`. For Eiswein personal use, type is typically `CLIENT_USER` or `SYSTEM_USER`.

**Transfer items (one per leg)**
Each item in `transferItems[]` is one side of a value movement:
| Field | Type | Note |
|---|---|---|
| `instrument` | object | `{cusip, symbol, description, instrumentId, netChange, type}`. Same shape as order legs. For cash movements, `instrument.type` is `SWEEP_VEHICLE` / `CASH_EQUIVALENT`. |
| `amount` | decimal | Quantity (shares for equity, dollars for cash). |
| `cost` | decimal | Cost basis per share. |
| `price` | decimal | Execution price per share. |
| `feeType` | enum | `COMMISSION`, `SEC_FEE`, `STR_FEE`, `R_FEE`, `CDSC_FEE`, `OPT_REG_FEE`, `ADDITIONAL_FEE`, `MISCELLANEOUS_FEE`, `FTT`, `FUTURES_CLEARING_FEE`, `FUTURES_DESK_OFFICE_FEE`, `FUTURES_EXCHANGE_FEE`, `FUTURES_GLOBEX_FEE`, `FUTURES_NFA_FEE`, `FUTURES_PIT_BROKERAGE_FEE`, `FUTURES_TRANSACTION_FEE`, `LOW_PROCEEDS_COMMISSION`, `BASE_CHARGE`, `GENERAL_CHARGE`, `GST_FEE`, `TAF_FEE`, `INDEX_OPTION_FEE`, `TEFRA_TAX`, `STATE_TAX`, `UNKNOWN`. |
| `positionEffect` | enum | `OPENING`, `CLOSING`, `AUTOMATIC`. |

---

## `GET /accounts/{accountNumber}/transactions`

**Purpose**: "All transactions for a specific account."

**Limits**: **Max 3000 transactions per response. Max date range 1 year.** For longer history, paginate by date.

### Path Parameters
| Name | Type | Required | Notes |
|---|---|---|---|
| `accountNumber` | string (path) | **yes** | Encrypted hashValue. |

### Query Parameters
| Name | Type | Required | Notes |
|---|---|---|---|
| `startDate` | string (query) | **yes** | ISO-8601 `yyyy-MM-dd'T'HH:mm:ss.SSSZ`. Example: `2024-03-28T21:10:42.000Z`. Inclusive. |
| `endDate` | string (query) | **yes** | Same format. Inclusive. Range ≤ 1 year. |
| `symbol` | string (query) | no | Filter by symbol. **URL-encode special characters** (e.g., options symbols with spaces). |
| `types` | string (query) | **yes** | One of the `type` enum values (see table above). Single value, not comma-separated per Swagger. |

### Response `200 application/json`

Array of canonical transaction objects.

### Eiswein usage

- **Phase S2 OAuth-connect seed**: On first Schwab connect, call with `types=TRADE&startDate=<1 year ago>&endDate=<today>` to backfill the last year of trades into the `Position` and `Trade` tables. This bootstraps Eiswein's view of the user's current holdings and cost basis without asking for manual entry.
- **Idempotent import**: Use `activityId` as the unique key — safe to re-run the backfill without double-counting.
- **Paginate** by narrowing `[startDate, endDate]` if a user hits the 3000-row cap (rare for personal accounts).
- For multiple `type` values, make parallel calls (one per type), since the query takes a single enum.

---

## `GET /accounts/{accountNumber}/transactions/{transactionId}`

**Purpose**: "Specific transaction information for a specific account."

### Path Parameters
| Name | Type | Required | Notes |
|---|---|---|---|
| `accountNumber` | string (path) | **yes** | Encrypted hashValue. |
| `transactionId` | integer (int64, path) | **yes** | The `activityId` from the list endpoint. |

### Query Parameters
None.

### Response `200 application/json`

Single canonical transaction object. (Swagger renders it as an array in the example, but a single ID returns one object — confirm at integration time.)

### Eiswein usage

- Drill-down for the Positions page's trade log — click a row to see full transaction details (rep, settlement, individual transfer legs).
- Rare call path; most trade detail comes from the list endpoint.

---

## Cross-references
- Account hash prerequisite: `accounts.md`
- Order-linked transactions: `orders.md` (`orderActivityCollection[].executionLegs[]` vs. this endpoint's `transferItems[]` — Schwab duplicates the fill info in both places)
- Streaming alternative: `streamer.md` §`ACCT_ACTIVITY` (preferred for real-time; this REST endpoint is the historical/reconciliation path)
