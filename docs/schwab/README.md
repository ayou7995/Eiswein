# Schwab API — Documentation Index

Organized Swagger-style docs for the Schwab Developer Portal APIs Eiswein consumes. Captured from the official portal (and one vetted community source for wire-protocol details that predate the portal publish).

---

## Files

| File | Covers | Status |
|---|---|---|
| [`security_reference.md`](security_reference.md) | **Authoritative** verbatim transcription of Schwab's "Schwab & API Security" doc — OAuth 4-step flow, token lifetimes, callback rules, order payload samples, instruction matrix, options symbology, rate limits. | ✅ Primary source. Wins over all other docs on conflicts. |
| [`oauth.md`](oauth.md) | Implementation-ready OAuth summary — exact URLs, header/body shapes, `%40` decoding, refresh cadence, Eiswein route handlers (`/start`, `/callback`, `/disconnect`). | ✅ Complete, fully sourced. |
| [`portal_guide.md`](portal_guide.md) | Schwab Developer Portal usage — registration, profile types, app lifecycle, callback URL rules, promote-to-production. | ✅ Complete. |
| [`accounts.md`](accounts.md) | Trader API account endpoints — `/accounts/accountNumbers` (hashValue mapping), `/accounts`, `/accounts/{hash}`. Position + balance field tables. | ✅ 3 endpoints complete. |
| [`orders.md`](orders.md) | Trader API order endpoints — 7 endpoints: GET list (per-account + cross-account), POST, GET/PUT/DELETE by id, previewOrder. Canonical order object + status enum. | ✅ 7 endpoints complete. |
| [`transactions.md`](transactions.md) | Trader API transaction history — `GET /accounts/{hash}/transactions`, `GET .../transactions/{id}`. Transaction object, transferItems, type enum, 3000-row / 1-year limits. | ✅ 2 endpoints complete. |
| [`userpreference.md`](userpreference.md) | Trader API `GET /userPreference` — **Streamer WebSocket prerequisite** (streamerSocketUrl, SchwabClientCustomerId, SchwabClientCorrelId, channel, function id). Also account nicknames + market-data entitlements. | ✅ Complete. |
| [`marketdata.md`](marketdata.md) | Market Data REST — `/quotes`, `/pricehistory`, `/markets`, `/instruments`. Optional replacement for yfinance + CUSIP/symbol lookup. | ✅ All relevant endpoints documented. Options/movers intentionally skipped. |
| [`streamer.md`](streamer.md) | WebSocket Streamer API — `LEVELONE_EQUITIES`, `ACCT_ACTIVITY`, error codes, reconnect state machine, Eiswein integration plan. | ✅ Reference complete. |

---

## Quick cross-reference

### Base URLs
- **OAuth**: `https://api.schwabapi.com/v1/oauth/{authorize,token}`
- **Trader (accounts / orders / transactions / userPreference)**: `https://api.schwabapi.com/trader/v1`
- **Market Data**: `https://api.schwabapi.com/marketdata/v1`
- **Streamer**: WebSocket URL from `GET /userPreference` (do not hardcode)

### Every response carries
- `Schwab-Client-CorrelId` header — log it on every call, include in support tickets.

### Standard status codes (Trader API)
`200` success · `400` validation · `401` auth / no linked accounts · `403` scope/role · `404` not found · `500` server error · `503` temporary.

### Common error envelope
```json
{ "message": "string", "errors": ["string"] }
```

### Account hash gotcha
Every Trader URL with `{accountNumber}` takes the **hashValue**, never plaintext. Fetch the mapping from `GET /accounts/accountNumbers` and cache it. See `accounts.md` §CRITICAL.

### Token lifetimes (Trader API, official)
- Access token: **30 min**
- Refresh token: **7 days**
- Refresh-invalidation triggers: expiry, user password reset, account-permission change.

### Order rate limits
- GET orders: **unthrottled**
- POST / PUT / DELETE / previewOrder: **0–120 / min per account** (app-configurable; email `TraderAPI@schwab.com`)
- Only `EQUITY` and `OPTION` supported for entry.

---

## Eiswein policy (at a glance)

| Capability | Eiswein uses? | Why |
|---|---|---|
| OAuth | ✅ Phase S1 | Required for any API call. |
| `/accounts` daily read | ✅ Phase S2 | Balances + positions reconciliation. |
| `/marketdata/v1/pricehistory` | 🟡 Optional (Phase S5) | Could replace yfinance; keeping yfinance for v1. |
| `/orders` GET (read-only) | 🟡 Phase S3 fallback | Reconcile fills when Streamer is dead > 5 min. |
| `/orders` POST / PUT / DELETE / previewOrder | ❌ **Never** | Eiswein is advisory-only. Human places orders in Schwab's own UI. |
| Streamer `ACCT_ACTIVITY` | ✅ Phase S3 | Push fills into Position table without polling. |
| Streamer `LEVELONE_EQUITIES` | 🟡 Phase S4 | Optional intraday stop-loss monitoring. |

---

## Pending documentation

**None.** All Schwab endpoints Eiswein needs for Phase S1–S5 are documented. Intentionally out of scope: options (`/chains`, `/expirationchain`), movers (`/movers`), Advisor Services, Data Aggregation LOBs.
