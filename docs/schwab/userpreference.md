# Schwab UserPreference API — Reference

**Source**: Schwab Developer Portal → Trader API - Individual → Accounts and Trading Production (Swagger)
**Captured**: 2026-04-21
**Status**: 1 endpoint fully documented.

Base URL: `https://api.schwabapi.com/trader/v1`

Auth: `Authorization: Bearer <access_token>`.

---

## ⚠️ Why this matters

**`GET /userPreference` is the mandatory prerequisite for every Streamer (WebSocket) connection.** Without the values it returns, the Streamer LOGIN frame has no valid `SchwabClientCustomerId` / `SchwabClientCorrelId` / channel identifiers and will be rejected. See `streamer.md` §2 (request/response model).

Call this **once on OAuth-connect**, cache the result, and re-fetch when:
- The refresh token is rotated (just to be safe).
- A Streamer LOGIN returns code 3 `LOGIN_DENIED` — the identifiers may have been rotated.
- Re-connecting after a long outage (> 24 h).

---

## `GET /userPreference`

**Purpose**: "Get user preference information for the logged in user."

### Parameters
**None.** No path, no query, no body.

### Response `200 application/json`

```json
[
  {
    "accounts": [
      {
        "accountNumber": "string",
        "primaryAccount": false,
        "type": "string",
        "nickName": "string",
        "accountColor": "string",
        "displayAcctId": "string",
        "autoPositionEffect": false
      }
    ],
    "streamerInfo": [
      {
        "streamerSocketUrl": "string",
        "schwabClientCustomerId": "string",
        "schwabClientCorrelId": "string",
        "schwabClientChannel": "string",
        "schwabClientFunctionId": "string"
      }
    ],
    "offers": [
      {
        "level2Permissions": false,
        "mktDataPermission": "string"
      }
    ]
  }
]
```

Note the outer array — the response is a **list** of preference documents. In practice there's one element; iterate to be safe.

### Field groups

**`accounts[]`** — one entry per linked Schwab account.
| Field | Type | Note |
|---|---|---|
| `accountNumber` | string | Plaintext. Use `/accounts/accountNumbers` to map to hashValue. |
| `primaryAccount` | bool | True for the user's designated primary account. |
| `type` | string | e.g. `BROKERAGE`, `IRA` — free-form per account. |
| `nickName` | string | User-set nickname (shown in Schwab app). Display in Eiswein UI for disambiguation. |
| `accountColor` | string | Hex or named — matches Schwab app color coding. Optional. |
| `displayAcctId` | string | Masked display form (e.g., `...1234`). Safe to show in UI. |
| `autoPositionEffect` | bool | If true, Schwab auto-classifies order `positionEffect`. |

**`streamerInfo[]`** — WebSocket connection config.
| Field | Type | Note |
|---|---|---|
| `streamerSocketUrl` | string | **The WebSocket URL** for the Streamer. Do NOT hardcode — re-fetch per `streamer.md` §10. |
| `schwabClientCustomerId` | string | Required in every Streamer command frame. |
| `schwabClientCorrelId` | string | Required in every Streamer command frame (different from the HTTP response `Schwab-Client-CorrelId` header). |
| `schwabClientChannel` | string | Streamer logical channel. |
| `schwabClientFunctionId` | string | Streamer function identifier. |

**`offers[]`** — market-data entitlements.
| Field | Type | Note |
|---|---|---|
| `level2Permissions` | bool | True if account is entitled to NYSE/NASDAQ Book data. Eiswein doesn't use Level 2 — inform UI only. |
| `mktDataPermission` | string | Tier label (e.g., `NP` = non-pro, `PRO` = professional). Controls whether quotes are real-time or delayed ~15 min. |

### Status codes
200 / 400 / 401 / 403 / 404 / 500 / 503. Standard error envelope `{message, errors[]}`. `Schwab-Client-CorrelId` on response header.

---

## Eiswein usage

**Phase S1 post-OAuth**:
1. Call `GET /userPreference` once after successfully exchanging the authorization code for tokens.
2. Persist into `BrokerCredential` (or a sibling `BrokerPreference` table):
   - `streamer_socket_url` (string)
   - `schwab_client_customer_id` (string, encrypted at rest — it's an opaque PII-adjacent identifier)
   - `schwab_client_correl_id` (string, encrypted at rest)
   - `schwab_client_channel`, `schwab_client_function_id`
   - `accounts_json` (encrypted — contains plaintext account numbers)
   - `mkt_data_permission` (string — gate real-time features on this)
3. Flag `is_realtime_quote_eligible = (mktDataPermission == "PRO")` for the UI — non-pro users see a "quotes delayed 15 min" banner on Ticker Detail.

**Phase S3 (Streamer)**:
- Use `streamerInfo[0].streamerSocketUrl` to open the WebSocket.
- Embed `schwabClientCustomerId`, `schwabClientCorrelId` in every frame per `streamer.md` §2.

**Re-fetch triggers**:
- On `12 CLOSE_CONNECTION` → reconnect with freshly fetched URL (URL may have rotated).
- On `3 LOGIN_DENIED` → refresh access token, then re-fetch `/userPreference`, then LOGIN.
- Daily sanity check: if the cached `streamerSocketUrl` is > 7 days old, re-fetch.

---

## Cross-references
- Streamer protocol: `streamer.md`
- Account hash mapping (pair plaintext `accountNumber` with hashValue): `accounts.md`
- OAuth prerequisite: `oauth.md`
