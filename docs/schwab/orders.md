# Schwab Orders API — Reference

**Source**: Schwab Developer Portal → Trader API - Individual → Accounts and Trading Production (Swagger)
**Captured**: 2026-04-21
**Status**: **7 order endpoints fully documented** from Swagger schemas.

Base URL: `https://api.schwabapi.com/trader/v1`

All endpoints require `Authorization: Bearer <access_token>`. For POST/PUT/DELETE also include `Accept: */*` and `Content-Type: application/json`.

**Path param note**: `{accountNumber}` is the **hashValue** from `/accounts/accountNumbers`, never the plaintext account number. See `accounts.md` §CRITICAL.

**Common response header on every call**: `Schwab-Client-CorrelId` (auto-generated). Log it.

**Common error envelope** and status codes (200/400/401/403/404/500/503) — see `accounts.md`.

---

## ⚠️ Eiswein Policy — Order Endpoints

**Eiswein is advisory-only. We do NOT place, modify, or cancel orders via API.** The human uses Schwab's own app to pull the trigger.

The only order endpoint Eiswein plans to use is **`GET /orders`** (and its per-account variant) — **read-only reconciliation**: compare what was filled against Eiswein's internal `Position` table so manual Schwab-UI trades don't drift out of sync. This is a Phase S3+ fallback when Streamer `ACCT_ACTIVITY` is unavailable.

Everything else in this doc is reference-only for potential future phases (S4+, heavily gated).

---

## Canonical Order Object (shared by GET/POST/PUT responses)

Every GET order response (list or single) returns objects with this shape:

```json
{
  "session": "NORMAL",
  "duration": "DAY",
  "orderType": "MARKET",
  "cancelTime": "2026-04-21T21:28:39.378Z",
  "complexOrderStrategyType": "NONE",
  "quantity": 0,
  "filledQuantity": 0,
  "remainingQuantity": 0,
  "requestedDestination": "INET",
  "destinationLinkName": "string",
  "releaseTime": "2026-04-21T21:28:39.378Z",
  "stopPrice": 0,
  "stopPriceLinkBasis": "MANUAL",
  "stopPriceLinkType": "VALUE",
  "stopPriceOffset": 0,
  "stopType": "STANDARD",
  "priceLinkBasis": "MANUAL",
  "priceLinkType": "VALUE",
  "price": 0,
  "taxLotMethod": "FIFO",
  "orderLegCollection": [
    {
      "orderLegType": "EQUITY",
      "legId": 0,
      "instrument": {
        "cusip": "string",
        "symbol": "string",
        "description": "string",
        "instrumentId": 0,
        "netChange": 0,
        "type": "SWEEP_VEHICLE"
      },
      "instruction": "BUY",
      "positionEffect": "OPENING",
      "quantity": 0,
      "quantityType": "ALL_SHARES",
      "divCapGains": "REINVEST",
      "toSymbol": "string"
    }
  ],
  "activationPrice": 0,
  "specialInstruction": "ALL_OR_NONE",
  "orderStrategyType": "SINGLE",
  "orderId": 0,
  "cancelable": false,
  "editable": false,
  "status": "AWAITING_PARENT_ORDER",
  "enteredTime": "2026-04-21T21:28:39.378Z",
  "closeTime": "2026-04-21T21:28:39.378Z",
  "tag": "string",
  "accountNumber": 0,
  "orderActivityCollection": [
    {
      "activityType": "EXECUTION",
      "executionType": "FILL",
      "quantity": 0,
      "orderRemainingQuantity": 0,
      "executionLegs": [
        {
          "legId": 0,
          "price": 0,
          "quantity": 0,
          "mismarkedQuantity": 0,
          "instrumentId": 0,
          "time": "2026-04-21T21:28:39.378Z"
        }
      ]
    }
  ],
  "replacingOrderCollection": ["string"],
  "childOrderStrategies": ["string"],
  "statusDescription": "string"
}
```

### Field groups

**Identity / routing**
- `orderId` (int64) — opaque ID
- `accountNumber` (int64) — plaintext on response (hash in URL)
- `tag` (string) — client-supplied label (optional)
- `requestedDestination` — `INET`, `ECN_ARCA`, `AUTO`, etc.
- `destinationLinkName` (string)

**Timing / session**
- `session` — `NORMAL`, `AM`, `PM`, `SEAMLESS`
- `duration` — `DAY`, `GOOD_TILL_CANCEL`, `FILL_OR_KILL`
- `enteredTime`, `releaseTime`, `cancelTime`, `closeTime` — ISO-8601 timestamps

**Pricing**
- `orderType` — `MARKET`, `LIMIT`, `STOP`, `STOP_LIMIT`, `TRAILING_STOP`, `NET_DEBIT`, `NET_CREDIT`, `NET_ZERO`
- `price`, `stopPrice`, `activationPrice` — decimals
- `priceLinkBasis` / `priceLinkType` — `MANUAL` / `VALUE` (for linked pricing)
- `stopPriceLinkBasis` / `stopPriceLinkType` / `stopPriceOffset` — trailing-stop mechanics
- `stopType` — `STANDARD`, `TRAILING`

**Strategy**
- `orderStrategyType` — `SINGLE`, `OCO`, `TRIGGER`, `OTA`, `OTOCO`
- `complexOrderStrategyType` — `NONE`, options combos
- `specialInstruction` — `ALL_OR_NONE`, `DO_NOT_REDUCE`, `ALL_OR_NONE_DO_NOT_REDUCE`
- `taxLotMethod` — `FIFO`, `LIFO`, `HIGH_COST`, `LOW_COST`, `AVERAGE_COST`, `SPECIFIC_LOT`
- `childOrderStrategies` (array) — nested orders for TRIGGER/OCO/OTOCO
- `replacingOrderCollection` (array) — history of orders this one replaced

**State**
- `status` (enum, see table below)
- `statusDescription` (string) — human-readable status reason
- `cancelable` (bool), `editable` (bool) — UI hints
- `filledQuantity`, `remainingQuantity` — execution progress
- `quantity` — original request qty

**Legs**
- `orderLegCollection[]` — one entry per leg (1 for single, 2+ for spreads)
  - `orderLegType` — `EQUITY`, `OPTION`
  - `legId` (int) — 1-based index within the order
  - `instrument` — `{cusip, symbol, description, instrumentId, netChange, type}`
    - `type` — `SWEEP_VEHICLE`, others TBD
  - `instruction` — `BUY`, `SELL`, `BUY_TO_OPEN`, `BUY_TO_CLOSE`, `SELL_TO_OPEN`, `SELL_TO_CLOSE`, `BUY_TO_COVER`, `SELL_SHORT` (see `security_reference.md` §Instruction Matrix)
  - `positionEffect` — `OPENING`, `CLOSING`, `AUTOMATIC`
  - `quantity` (int)
  - `quantityType` — `ALL_SHARES`, `DOLLARS`, `SHARES`
  - `divCapGains` — `REINVEST`, `PAYOUT`
  - `toSymbol` (string) — for corporate-action legs (rare)

**Execution tracking**
- `orderActivityCollection[]` — fills and partial fills
  - `activityType` — `EXECUTION`, `ORDER_ACTION`
  - `executionType` — `FILL`, `PARTIAL_FILL`, `CANCEL`, `REJECT`
  - `quantity`, `orderRemainingQuantity`
  - `executionLegs[]` — `{legId, price, quantity, mismarkedQuantity, instrumentId, time}`

### `status` enum (from Swagger)

| Value | Meaning |
|---|---|
| `AWAITING_PARENT_ORDER` | Child of TRIGGER/OTA waiting on parent. |
| `AWAITING_CONDITION` | Condition not yet met. |
| `AWAITING_STOP_CONDITION` | Stop not yet triggered. |
| `AWAITING_MANUAL_REVIEW` | Trade desk reviewing. |
| `ACCEPTED` | Accepted by Schwab, not yet routed. |
| `AWAITING_UR_OUT` | Processing an unsolicited route-out. |
| `PENDING_ACTIVATION` | Queued for market open. |
| `QUEUED` | Queued internally. |
| `WORKING` | Live at the exchange. |
| `REJECTED` | Denied (by Schwab or exchange). |
| `PENDING_CANCEL` | Cancel request in flight. |
| `CANCELED` | Canceled successfully. |
| `PENDING_REPLACE` | Replace in flight. |
| `REPLACED` | Replaced; see `replacingOrderCollection`. |
| `FILLED` | Fully filled. |
| `EXPIRED` | Time-in-force expired. |
| `NEW` | Just created. |
| `AWAITING_RELEASE_TIME` | Held for scheduled release. |
| `PENDING_ACKNOWLEDGEMENT` | Waiting for exchange ACK. |
| `PENDING_RECALL` | Recall in progress. |
| `UNKNOWN` | Fallback. |

**Eiswein reconciliation rule**: treat `FILLED` as authoritative for Position updates. Treat `PARTIAL_FILL` via `orderActivityCollection` deltas. Ignore transient states (`PENDING_*`, `AWAITING_*`, `WORKING`).

---

## `GET /accounts/{accountNumber}/orders`

**Purpose**: List orders for a single linked account.

### Path Parameters
| Name | Type | Required | Notes |
|---|---|---|---|
| `accountNumber` | string | **yes** | Encrypted hashValue. |

### Query Parameters
| Name | Type | Required | Notes |
|---|---|---|---|
| `fromEnteredTime` | string (ISO-8601) | yes | Inclusive lower bound. |
| `toEnteredTime` | string (ISO-8601) | yes | Inclusive upper bound. |
| `maxResults` | integer | no | Cap on results. |
| `status` | string | no | Filter by `status` enum value. |

### Response `200 application/json`

Array of canonical order objects (shape above).

### Eiswein usage
- Phase S3 fallback: when Streamer `ACCT_ACTIVITY` is dead > 5 min, poll this every 60s with `status=FILLED&fromEnteredTime=<last_check>`.
- Match returned orders to internal `Position` rows via `orderLegCollection[].instrument.symbol` + `orderActivityCollection[].executionLegs[].price` + `quantity`.

---

## `POST /accounts/{accountNumber}/orders`

**Purpose**: Place an order for a specific account.

### Headers (differ from GET)
```
Authorization: Bearer <access_token>
Accept: */*
Content-Type: application/json
```

### Path Parameters
| Name | Type | Required | Notes |
|---|---|---|---|
| `accountNumber` | string | **yes** | Encrypted hashValue. |

### Request body

Same shape as canonical order object, minus read-only fields (`orderId`, `status`, `statusDescription`, `filledQuantity`, `remainingQuantity`, `cancelable`, `editable`, `orderActivityCollection`, `replacingOrderCollection`, `enteredTime`, `closeTime`, `requestedDestination`). See `security_reference.md` §Order Payload Examples for minimal working payloads (Buy Market, Buy Limit, Vertical Spread, OCO, OTA, OTOCO, Trailing Stop).

### Response

`201 Created` with **no body** (order ID returned via `Location` header — standard REST pattern).

### Rate limit
0–120 requests/minute per account (configurable at App registration). Email `TraderAPI@schwab.com` to adjust.

### Eiswein usage
**None.** Not called from Eiswein. Placeholder only.

---

## `GET /accounts/{accountNumber}/orders/{orderId}`

**Purpose**: Get a single order by ID.

### Path Parameters
| Name | Type | Required | Notes |
|---|---|---|---|
| `accountNumber` | string | **yes** | Encrypted hashValue. |
| `orderId` | int64 | **yes** | From prior GET/POST. |

### Response `200 application/json`

Single canonical order object.

### Eiswein usage
Reference only. If we ever add an "Order Status" page for the human, this is the lookup.

---

## `DELETE /accounts/{accountNumber}/orders/{orderId}`

**Purpose**: Cancel a working order.

### Path Parameters
Same as GET-by-id.

### Response
`200 OK` on success; order transitions to `PENDING_CANCEL` then `CANCELED`.

### Rate limit
Counts toward the 0–120/min cap.

### Eiswein usage
**None.** Cancels are human-initiated in Schwab's app.

---

## `PUT /accounts/{accountNumber}/orders/{orderId}`

**Purpose**: Replace (modify) a working order. Schwab cancels the original and creates a new order atomically.

### Headers
Same as POST (requires `Content-Type: application/json`).

### Path Parameters
Same as GET-by-id.

### Request body

Same shape as POST — the **full replacement order**, not a patch. Missing fields are treated as removed.

### Response
`201 Created`. Original order status becomes `REPLACED`; see `replacingOrderCollection` on the new order for linkage.

### Rate limit
Counts toward the 0–120/min cap.

### Eiswein usage
**None.**

---

## `GET /orders`

**Purpose**: List orders across **all** linked accounts for the logged-in user.

### Query Parameters
Same as per-account variant:
| Name | Type | Required |
|---|---|---|
| `fromEnteredTime` | ISO-8601 | yes |
| `toEnteredTime` | ISO-8601 | yes |
| `maxResults` | integer | no |
| `status` | enum | no |

### Response `200 application/json`

Array of canonical order objects, each with its own `accountNumber` (plaintext in body).

### Eiswein usage
- For a **single-account** Eiswein user (our default), `/accounts/{hash}/orders` is simpler — no fan-out.
- For a **multi-account** user, this is the right call for global fill reconciliation.
- Today we default to the per-account form.

---

## `POST /accounts/{accountNumber}/previewOrder`

**Purpose**: **Dry-run** an order without placing it. Returns projected commission, buying-power impact, and validation results (accepts/alerts/rejects/reviews/warns). Essential for UI "Confirm order" screens.

### Headers
Same as POST.

### Path Parameters
| Name | Type | Required | Notes |
|---|---|---|---|
| `accountNumber` | string | **yes** | Encrypted hashValue. |

### Request body

```json
{
  "orderId": 0,
  "orderStrategy": {
    "accountNumber": "string",
    "advancedOrderType": "NONE",
    "closeTime": "2026-04-21T21:35:03.032Z",
    "enteredTime": "2026-04-21T21:35:03.032Z",
    "orderBalance": {
      "orderValue": 0,
      "projectedAvailableFund": 0,
      "projectedBuyingPower": 0,
      "projectedCommission": 0
    },
    "orderStrategyType": "SINGLE",
    "orderVersion": 0,
    "session": "NORMAL",
    "status": "AWAITING_PARENT_ORDER",
    "allOrNone": true,
    "discretionary": true,
    "duration": "DAY",
    "filledQuantity": 0,
    "orderType": "MARKET",
    "orderValue": 0,
    "price": 0,
    "quantity": 0,
    "remainingQuantity": 0,
    "sellNonMarginableFirst": true,
    "settlementInstruction": "REGULAR",
    "strategy": "NONE",
    "amountIndicator": "DOLLARS",
    "orderLegs": [
      {
        "askPrice": 0,
        "bidPrice": 0,
        "lastPrice": 0,
        "markPrice": 0,
        "projectedCommission": 0,
        "quantity": 0,
        "finalSymbol": "string",
        "legId": 0,
        "assetType": "EQUITY",
        "instruction": "BUY"
      }
    ]
  },
  "orderValidationResult": {
    "alerts": [],
    "accepts": [],
    "rejects": [],
    "reviews": [],
    "warns": []
  },
  "commissionAndFee": { ... }
}
```

**Note**: Preview uses a **richer order shape** than POST. It separates the order into `orderStrategy` (the order itself) and the metadata (`orderBalance`, `orderValidationResult`, `commissionAndFee`) that Schwab computes server-side.

### Preview-specific enums
- `advancedOrderType` — `NONE`, `OTO`, `OCO`, `OTOCO`, `TRIGGER`
- `settlementInstruction` — `REGULAR`, `CASH`, `NEXT_DAY`
- `strategy` — `NONE`, options-strategy names
- `amountIndicator` — `DOLLARS`, `SHARES`, `ALL_SHARES`
- `allOrNone` (bool), `discretionary` (bool), `sellNonMarginableFirst` (bool)

### Preview-specific leg fields
Each `orderLegs[]` item includes live-quote snapshot + projected commission:
- `askPrice`, `bidPrice`, `lastPrice`, `markPrice` — current quote
- `projectedCommission` — per-leg commission estimate
- `finalSymbol` — resolved symbol (after fractional routing, corp actions)
- `assetType` — `EQUITY`, `OPTION`
- `instruction` — see Instruction Matrix

### Response `200 application/json`

Same shape as the request body — Schwab fills in the server-computed fields:
- `orderStrategy.orderBalance.{orderValue, projectedAvailableFund, projectedBuyingPower, projectedCommission}`
- `orderValidationResult.{alerts, accepts, rejects, reviews, warns}[]`
- `commissionAndFee.{commission, fee, trueCommission}`

### `orderValidationResult` entry shape
```json
{
  "validationRuleName": "string",
  "message": "string",
  "activityMessage": "string",
  "originalSeverity": "ACCEPT",
  "overrideName": "string",
  "overrideSeverity": "ACCEPT"
}
```

- `alerts[]` — non-blocking warnings
- `accepts[]` — rules explicitly accepted
- `rejects[]` — **blocking errors** — the order will not be placed
- `reviews[]` — flagged for manual review
- `warns[]` — advisory

Severity enum: `ACCEPT`, `WARN`, `REVIEW`, `REJECT`, `ALERT`.

### `commissionAndFee` shape
Three parallel trees, same schema:
- `commission` — Schwab commission breakdown
- `fee` — regulatory/exchange fees (SEC, TAF, etc.)
- `trueCommission` — actual post-rebate net

Each has `{commission,fee,trueCommission}Legs[].commissionValues[].{value, type}` where `type` ∈ `COMMISSION`, `SEC_FEE`, `TAF`, `OPTION_REG_FEE`, etc.

### Eiswein usage
**None today.** Future consideration: if Eiswein ever adds a "one-tap copy to Schwab" feature, preview would let us show the user the projected commission and buying-power impact before they confirm — but this is S4+ and out of current scope.

---

## Rate limits (repeated here for convenience)

- **PUT / POST / DELETE orders (including previewOrder)**: 0 – 120 requests per minute per account. Configurable at App registration.
- **GET orders**: **unthrottled**.
- Only `EQUITY` and `OPTION` asset types support order entry.
- Email `TraderAPI@schwab.com` to adjust.

See `security_reference.md` §Rate Limits and §Instruction Matrix for the full story.

---

## Cross-references

- OAuth / auth header: `oauth.md`
- Account-hash prerequisite, balance/position shapes: `accounts.md`
- Full order JSON examples (Buy Market, Buy Limit Option, Vertical Spread, OCO, OTA, OTOCO, Trailing Stop): `security_reference.md` §Order Payload Examples
- Streaming fills (preferred over polling these endpoints): `streamer.md` §5 `ACCT_ACTIVITY`
