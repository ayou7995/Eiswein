# Schwab & API Security — Official Reference

**Source**: Schwab Developer Portal → API Products → Trader API - Individual → Accounts and Trading Production → "Schwab & API Security"
**Captured**: 2026-04-21 (verbatim transcription of the official product-page section)
**Status**: **AUTHORITATIVE**. This is the primary source. `oauth.md` is our implementation-oriented summary built on top of this.

If `oauth.md` and this doc ever disagree, **this doc wins** — update `oauth.md` to match.

---

## OAuth 2 Overview

Schwab employs the **OAuth 2** protocol to secure services from unauthorized access. The implementation adheres to current IETF standards:

- OAuth 2: [RFC 6749](https://tools.ietf.org/html/rfc6749)
- Bearer Token: [RFC 6750](https://tools.ietf.org/html/rfc6750)

Bearer tokens are used for the `authorization_code` Grant Type.

---

## Three-Legged Workflow

Lets Users grant an App permission to access Protected Resources without disclosing credentials. User is directed to Schwab's **Login Micro Site (LMS)** for Consent and Grant (CAG), then redirected back to the Application.

### Key Terms

| Term | Definition |
|---|---|
| **App** | OAuth registration on the Dev Portal. Owned by a Company. |
| **Client ID & Client Secret** | Generated when an App is approved. Client Secret must be kept confidential. |
| **Callback URL (`redirect_uri`)** | Application's landing-page host. Requirements below. |
| **Display Name** | App name shown during CAG — ensures user grants consent to the correct App. |
| **Environment** | Sandbox (test data) or Production (live data). Trader API Sandbox "available later this year". |
| **Product Subscription** | An App subscribes to **exactly one** API Product (e.g., Trader API - Individual). |
| **Third-Party Application** | The User-Agent (website/app) using the Bearer token. Different from the "App" registration. |
| **CAG** | Consent and Grant — user action on LMS. |
| **LMS** | Login Micro Site — where users log in during OAuth. |
| **LOB** | Line of Business — owner of an API Product. |
| **User** | Resource Owner per RFC 6749 §1.1. |

### Callback URL Rules (OFFICIAL)

- **Must be HTTPS.** (No HTTP, no custom schemes.)
- Multiple URLs supported, separated by comma.
- **255 character limit** total, including all URLs listed.
- Localhost is acceptable: `https://127.0.0.1`.

### Token types

| Token | Lifetime | Purpose |
|---|---|---|
| **Access Token** | **30 minutes** (Trader API) | `Authorization: Bearer {access_token}` on API calls. |
| **Bearer Token** | Same as Access Token — just the name for when it's in the header. | |
| **Refresh Token** | **7 days** (Trader API) | Mint new access tokens. On expiry, restart full OAuth flow (CAG/LMS). |

Refresh Token invalidation triggers: expiry, **user password reset**, or other security changes.

---

## Three-Legged Flow — Entities

1. **Resource Owner (User)** — Schwab Client granting access.
2. **OAuth Client (App)** — Dev Portal App, uses Client ID + Client Secret.
3. **User-Agent** — 3rd-party application/website interacting with APIs.
4. **Authorization Server** — Schwab OAuth server issuing tokens.
5. **Resource Server** — Schwab server hosting Protected Resources.

---

## Step 1: App Authorization

Direct the user's browser to:

```
GET https://api.schwabapi.com/v1/oauth/authorize
  ?client_id={CONSUMER_KEY}
  &redirect_uri={APP_CALLBACK_URL}
```

After CAG completes on LMS, Schwab redirects to:

```
https://{APP_CALLBACK_URL}/?code={AUTHORIZATION_CODE_GENERATED}&session={SESSION_ID}
```

**Notes**:
- The destination may show as a 404 page — the browser address bar contains the `code`.
- The `code` contains an `@` URL-encoded as `%40`. Must **URL-decode** before use in Step 2.

---

## Step 2: Access Token Creation

```
POST https://api.schwabapi.com/v1/oauth/token
```

**Headers**:
```
Authorization: Basic {BASE64_ENCODED_ClientID:ClientSecret}
Content-Type: application/x-www-form-urlencoded
```

**Body** (form):
```
grant_type=authorization_code
code={URL_DECODED_AUTHORIZATION_CODE}
redirect_uri={APP_CALLBACK_URL}
```

### Response (official example)

```json
{
  "expires_in": 1800,
  "token_type": "Bearer",
  "scope": "api",
  "refresh_token": "{REFRESH_TOKEN_HERE}",
  "access_token": "{ACCESS_TOKEN_HERE}",
  "id_token": "{JWT_HERE}"
}
```

- `expires_in` = seconds the access_token is valid (1800s = 30 min).
- `scope` = `"api"` for Trader API (single flat scope — we don't need to request it).
- `id_token` = JWT, currently ignored by Eiswein.

---

## Step 3: Make an API Call

```
Authorization: Bearer {access_token}
```

Example:
```
Authorization: Bearer I0.kC95zyI039S-YTEw=
```

---

## Step 4: Refresh an Access Token

```
POST https://api.schwabapi.com/v1/oauth/token
```

**Headers**: same Basic Auth as Step 2.

**Body**:
```
grant_type=refresh_token
refresh_token={REFRESH_TOKEN_GENERATED_FROM_PRIOR_STEP}
```

**Response**: same shape as Step 2 (new `access_token`, possibly new `refresh_token`).

**When to use refresh vs. full restart (per Schwab):**
- Refresh Token step works **before** an access_token expires — proactive refresh is fine.
- Once the refresh token is **expired (7 days)** or **invalidated (e.g., user password reset)**, Step 4 fails and Steps 1+2 must be repeated.

---

## Rate Limits (Order Endpoints)

- **Order submission limits are configurable per application** at registration (or via follow-up).
- Range: **0 to 120 requests per minute per account** for PUT / POST / DELETE order requests.
- **GET order requests are unthrottled.**
- Contact: `TraderAPI@schwab.com` to adjust limits.

Eiswein is advisory-only (no order placement). Default throttle value doesn't matter for us.

---

## Order Entry — Supported Asset Types

Only `EQUITY` and `OPTION` supported. No mutual funds, no fixed income via API.

### Instruction Matrix

| Instruction | EQUITY (Stocks/ETFs) | OPTION |
|---|---|---|
| `BUY` | ✅ | ❌ |
| `SELL` | ✅ | ❌ |
| `BUY_TO_OPEN` | ❌ | ✅ |
| `BUY_TO_COVER` | ✅ | ❌ |
| `BUY_TO_CLOSE` | ❌ | ✅ |
| `SELL_TO_OPEN` | ❌ | ✅ |
| `SELL_SHORT` | ✅ | ❌ |
| `SELL_TO_CLOSE` | ❌ | ✅ |

### Options Symbology

Format: `{Underlying 6 chars w/ spaces}{Expiration YYMMDD}{C|P}{Strike 8 chars = 5 dollars + 3 decimals × 1000}`

Examples:
- `XYZ   210115C00050000` → XYZ, 2021-01-15, Call, $50.00
- `XYZ   210115C00062500` → XYZ, 2021-01-15, Call, $62.50

---

## Order Payload Examples (verbatim from Schwab)

Eiswein doesn't place orders. Keep these for future reference only.

### Buy Market — Stock
```json
{
  "orderType": "MARKET",
  "session": "NORMAL",
  "duration": "DAY",
  "orderStrategyType": "SINGLE",
  "orderLegCollection": [
    {
      "instruction": "BUY",
      "quantity": 15,
      "instrument": {"symbol": "XYZ", "assetType": "EQUITY"}
    }
  ]
}
```

### Buy Limit — Single Option
```json
{
  "complexOrderStrategyType": "NONE",
  "orderType": "LIMIT",
  "session": "NORMAL",
  "price": "6.45",
  "duration": "DAY",
  "orderStrategyType": "SINGLE",
  "orderLegCollection": [
    {
      "instruction": "BUY_TO_OPEN",
      "quantity": 10,
      "instrument": {"symbol": "XYZ   240315C00500000", "assetType": "OPTION"}
    }
  ]
}
```

### Vertical Call Spread
```json
{
  "orderType": "NET_DEBIT",
  "session": "NORMAL",
  "price": "0.10",
  "duration": "DAY",
  "orderStrategyType": "SINGLE",
  "orderLegCollection": [
    {"instruction": "BUY_TO_OPEN", "quantity": 2, "instrument": {"symbol": "XYZ   240315P00045000", "assetType": "OPTION"}},
    {"instruction": "SELL_TO_OPEN", "quantity": 2, "instrument": {"symbol": "XYZ   240315P00043000", "assetType": "OPTION"}}
  ]
}
```

### One-Triggers-Another (OTA)
```json
{
  "orderType": "LIMIT", "session": "NORMAL", "price": "34.97", "duration": "DAY",
  "orderStrategyType": "TRIGGER",
  "orderLegCollection": [
    {"instruction": "BUY", "quantity": 10, "instrument": {"symbol": "XYZ", "assetType": "EQUITY"}}
  ],
  "childOrderStrategies": [
    {
      "orderType": "LIMIT", "session": "NORMAL", "price": "42.03", "duration": "DAY",
      "orderStrategyType": "SINGLE",
      "orderLegCollection": [
        {"instruction": "SELL", "quantity": 10, "instrument": {"symbol": "XYZ", "assetType": "EQUITY"}}
      ]
    }
  ]
}
```

### One-Cancels-Another (OCO)
```json
{
  "orderStrategyType": "OCO",
  "childOrderStrategies": [
    {
      "orderType": "LIMIT", "session": "NORMAL", "price": "45.97", "duration": "DAY",
      "orderStrategyType": "SINGLE",
      "orderLegCollection": [{"instruction": "SELL", "quantity": 2, "instrument": {"symbol": "XYZ", "assetType": "EQUITY"}}]
    },
    {
      "orderType": "STOP_LIMIT", "session": "NORMAL", "price": "37.00", "stopPrice": "37.03", "duration": "DAY",
      "orderStrategyType": "SINGLE",
      "orderLegCollection": [{"instruction": "SELL", "quantity": 2, "instrument": {"symbol": "XYZ", "assetType": "EQUITY"}}]
    }
  ]
}
```

### One-Triggers-One-Cancels-Another (OTOCO)
Same TRIGGER-then-OCO pattern — see verbatim JSON in Schwab's docs for nested structure.

### Trailing Stop (Stock)
```json
{
  "complexOrderStrategyType": "NONE",
  "orderType": "TRAILING_STOP",
  "session": "NORMAL",
  "stopPriceLinkBasis": "BID",
  "stopPriceLinkType": "VALUE",
  "stopPriceOffset": 10,
  "duration": "DAY",
  "orderStrategyType": "SINGLE",
  "orderLegCollection": [
    {"instruction": "SELL", "quantity": 10, "instrument": {"symbol": "XYZ", "assetType": "EQUITY"}}
  ]
}
```

Additional enum values observed in these samples:
- `duration`: `DAY`, `GOOD_TILL_CANCEL`
- `orderType`: `MARKET`, `LIMIT`, `STOP`, `STOP_LIMIT`, `TRAILING_STOP`, `NET_DEBIT`
- `orderStrategyType`: `SINGLE`, `TRIGGER`, `OCO`
- `stopPriceLinkBasis`: `BID`
- `stopPriceLinkType`: `VALUE`

---

## Key Differences Between This Doc and Community Sources

Now that we have the authoritative source, correct these previously-uncertain points:

| Fact | Previously | Now OFFICIAL |
|---|---|---|
| Refresh token TTL | "community-reported 7 days" | **Officially 7 days** |
| Callback URL must be HTTPS | "some LOBs require" | **Required by Trader API** |
| Callback URL char limit | 256 (per User Guides) | **255** (per this doc) — honour the smaller value |
| `scope` value | unknown | **`"api"`** (single flat scope, returned in response, no need to send in request) |
| `id_token` in response | not mentioned | **Present** (JWT, ignore for now) |
| Refresh-invalidation triggers | guessed | **User password reset** is explicitly called out |
| Order rate limits | unknown | **0–120/min per account**; get-orders unthrottled; email TraderAPI@schwab.com to adjust |
| Supported assetTypes for orders | unknown | **EQUITY and OPTION only** |
