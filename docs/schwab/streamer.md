# Schwab Streamer API — Reference & Eiswein Integration Notes

**Source**: Schwab Developer Portal → Market Data Production → Streamer API
**Captured**: 2026-04-20 (initial)
**Status**: reference only — no code in Eiswein touches the Streamer yet. Integration plan at the bottom.

---

## 1. What the Streamer Is

A **WebSocket** service that pushes JSON-formatted market data and account activity. It is the *push / real-time* side of Schwab's API. There is also a **REST API** for snapshot quotes, history, orders, and the OAuth dance — that's documented separately and is what Eiswein will need first.

Auth: every Streamer connection is authenticated with an **access token** (15-min lifetime) obtained from the REST `POST /v1/oauth/token` endpoint. Plus two identifiers (`schwabClientCustomerId`, `schwabClientCorrelId`) fetched once from the REST `GET User Preference` endpoint.

Connection limit: **1 concurrent Streamer connection per Schwab user**. If Eiswein opens a second one, the first is closed (error code `12 CLOSE_CONNECTION`).

---

## 2. Request / Response Model

- Every frame is a JSON object with a `requests` array (up to N commands batched) or a single `request` for a one-off.
- Each command carries: `service`, `command` (`LOGIN`/`SUBS`/`ADD`/`UNSUBS`/`VIEW`/`LOGOUT`), `requestid` (client-chosen unique int), `SchwabClientCustomerId`, `SchwabClientCorrelId`, and `parameters`.
- Server emits three frame shapes: `response` (acks), `notify` (heartbeats), `data` (streaming payloads).
- Must **wait for LOGIN success** before issuing any other command or Schwab returns `20 STREAM_CONN_NOT_FOUND`.

### Commands cheat-sheet
| Command | Use when |
|---|---|
| `LOGIN` | First frame after WebSocket open. |
| `SUBS` | Replace the entire subscription list for a service. |
| `ADD` | Incrementally add symbols (no wipe). |
| `UNSUBS` | Remove a symbol. |
| `VIEW` | Change the subscribed field list for a service. |
| `LOGOUT` | Clean shutdown. |

---

## 3. Services — What We Care About

| Service | Delivery | Eiswein relevance |
|---|---|---|
| `LEVELONE_EQUITIES` | Change | **High** — real-time bid/ask/last/volume for watchlist tickers. Could replace yfinance for intraday stop-loss monitoring. |
| `ACCT_ACTIVITY` | All Sequence | **High** — order fills + transfers push into our Position table (no polling needed). |
| `CHART_EQUITY` | All Sequence | Medium — 1-minute OHLCV candles. Useful for intraday view if we ever add one. |
| `LEVELONE_OPTIONS` | Change | **Skip** — Eiswein doesn't trade options. |
| `LEVELONE_FUTURES` | Change | Skip. |
| `LEVELONE_FUTURES_OPTIONS` | Change | Skip. |
| `LEVELONE_FOREX` | Change | Skip (DXY comes from FRED). |
| `NYSE_BOOK` / `NASDAQ_BOOK` / `OPTIONS_BOOK` | Whole | Skip — Level 2 data is not used by any of our 12 indicators. |
| `CHART_FUTURES` | All Sequence | Skip. |
| `SCREENER_EQUITY` / `SCREENER_OPTION` | Whole | Skip — we don't do gainers/losers screens. |

**Two services matter for now: `LEVELONE_EQUITIES` and `ACCT_ACTIVITY`.** Everything else we can ignore.

---

## 4. `LEVELONE_EQUITIES` — Essential Field Map

Streamer returns fields by **numeric ID**, not names — you have to decode them. These are the fields Eiswein cares about. Full 55-field list is in the raw Schwab doc if we ever need more.

| ID | Field | Use |
|---|---|---|
| 0 | Symbol | key (always present as `"key"` in payload) |
| 1 | Bid Price | quote display / spread |
| 2 | Ask Price | quote display / spread |
| 3 | Last Price | intraday stop-loss check, "current_price" on Position |
| 8 | Total Volume | volume anomaly indicator |
| 10 | Day High | high-of-day reference |
| 11 | Day Low | low-of-day reference |
| 12 | Prev Close | % change calc |
| 17 | Open Price | today's open |
| 18 | Net Change | `last - prev_close` |
| 28 | Regular Market Trade? | filter out pre/post-market |
| 33 | Security Status | `Normal` / `Halted` / `Closed` — important for stop-loss logic |
| 35 | Trade Time (ms epoch) | freshness check |
| 42 | Net % Change | % display |
| 49 | Shortable | optional |

**Subscribe shape**: `fields: "0,1,2,3,8,10,11,12,17,18,28,33,35,42"` — 14 fields is enough for the Eiswein surface.

Also emitted unconditionally: `key`, `delayed`, `assetMainType`, `assetSubType`, `cusip`. Useful to detect `delayed=true` (our account tier matters here — if it's non-pro, quotes are delayed ~15 min and we should gate real-time-dependent features).

---

## 5. `ACCT_ACTIVITY` — Push Into the Position Table

Subscribe with `fields: "0,1,2,3"` and a single key (they only use the first one).

| Field | Type | Meaning |
|---|---|---|
| `seq` | int | Message number. Used for dedup on reconnect — if we see the same `seq` twice, drop it. |
| `key` | str | Our echoed subscription key. |
| 1 | str | Account number the event hit. |
| 2 | str | Message Type (see below). |
| 3 | str | Message Data — JSON payload that matches Message Type. Or plain text on `ERROR`. |

Message Types we'd handle: `OrderRoute`, `OrderAccepted`, `OrderRejected`, `ExecutionRequestCreated`, `ExecutionRequestCompleted`, `CancelAccepted`, and the critical one — **fills** arrive as execution events. Eiswein's Position repo `apply_buy` / `apply_sell` would be called here instead of (or in addition to) the manual UI forms in PositionsPage.

Other types (transfers, journal entries, corporate actions) can be logged to AuditLog for traceability without updating Position.

---

## 6. Error Codes That Affect Our Connection Logic

Only the ones that change behavior — full table is in the raw doc.

| Code | Meaning | Connection Severed? | Our handler |
|---|---|---|---|
| 0 | SUCCESS | No | Log debug. |
| 3 | LOGIN_DENIED | **Yes** | Refresh the access token via REST, reconnect. |
| 11 | SERVICE_NOT_AVAILABLE | No | Retry with exponential backoff. |
| 12 | CLOSE_CONNECTION | **Yes** | Another client opened a connection. Either Eiswein has two instances running (bug) or the user logged in via schwab.com. Back off and reconnect after a delay. |
| 19 | REACHED_SYMBOL_LIMIT | No | Cap subscriptions. |
| 20 | STREAM_CONN_NOT_FOUND | TBD | Race: we sent SUBS before LOGIN finished. Wait for LOGIN `response` with `code:0` before any SUBS. |
| 21 | BAD_COMMAND_FORMAT | No | Bug in our client — log and investigate. |
| 30 | STOP_STREAMING | **Yes** | No active subscriptions or admin shutdown. Re-login only if we actually want to re-subscribe. |

All "Severed" codes need a reconnect state machine with backoff. Minimum logic: exponential backoff 2s → 4s → 8s → 16s → 32s (cap), and fall back to REST polling if Streamer fails > 5 min.

---

## 7. Heartbeats

`{"notify":[{"heartbeat":"1668715930582"}]}` — arrives every ~20s. No response required from client. Treat as liveness. If we go > 60s without a heartbeat *and* no data, treat the connection as dead and reconnect.

---

## 8. What We're Missing (needs separate docs)

These were NOT in the dump — we need them before any Schwab code lands:

1. **OAuth flow** — Authorization URL, `POST /v1/oauth/token` contract, refresh-token lifetime, PKCE requirements. Eiswein already has `BrokerCredential` with AES-256-GCM encryption ready for the refresh token.
2. **REST base URL for production vs sandbox.**
3. **`GET User Preference` endpoint** — returns `schwabClientCustomerId`, `schwabClientCorrelId`, **WebSocket URL**, and channel ID. Mandatory before the Streamer works.
4. **REST market-data endpoints** — `/marketdata/v1/quotes`, `/pricehistory`, etc. — needed if we want Schwab quotes as the primary source (replacing yfinance).
5. **REST account endpoints** — `/trader/v1/accounts`, `/orders`. Needed for initial Position sync.
6. **Rate limits** — requests per second, burst allowance, per-endpoint variations.

Paste those docs next and we add `docs/schwab/oauth.md`, `docs/schwab/accounts.md`, `docs/schwab/marketdata.md` in the same folder.

---

## 9. Eiswein Integration Plan (Phased)

**Phase S1 — OAuth + token storage** (prerequisite for everything)
- REST OAuth exchange in `backend/app/datasources/schwab_source.py` (currently stub).
- Persist refresh token → `BrokerCredential.encrypted_refresh_token` (already wired, AES-256-GCM).
- Token refresh job: run every 20 min (access token TTL is 30 min) and every 7 days for the refresh token.
- User-facing: settings page → "Connect Schwab" button → OAuth redirect → callback endpoint.

**Phase S2 — Account sync (REST)**
- Read account ID + balances via REST on OAuth-complete and once per day.
- Read current positions via REST and reconcile against Eiswein's Position table. Detect drift (user bought outside Eiswein).

**Phase S3 — `ACCT_ACTIVITY` stream (WebSocket)**
- Open the Streamer connection inside the existing APScheduler (or a separate background task).
- Subscribe `ACCT_ACTIVITY`. On fill → call `PositionRepository.apply_buy/apply_sell` → emit AuditLog.
- Reconnect + backoff state machine. Fallback: if Streamer is dead for > 5 min, fall back to REST polling `/orders?status=FILLED`.

**Phase S4 — `LEVELONE_EQUITIES` stream** (optional enhancement)
- Subscribe watchlist symbols at market open; unsub at close.
- Feed Last Price into an intraday stop-loss checker (already planned as `intra_day_stop_loss` job in CLAUDE.md).
- This is the most ambitious piece — real-time stop-loss alerts via email/push.

**Phase S5 — Schwab as primary market-data source** (optional)
- Replace yfinance in `daily_ingestion.py` with Schwab REST `/pricehistory`.
- Keeps FRED for macro (Schwab doesn't provide those series).

---

## 10. Security Notes

- Access token (15-min TTL): keep in memory only, never persist.
- Refresh token (7-day TTL, per Schwab public docs): store encrypted in `BrokerCredential` (already done).
- Never log either token. `log_sanitizer` already redacts fields named `token`/`secret`/etc. — verify before any logging touches Schwab code.
- WebSocket URL from User Preference can change — re-fetch on reconnect, don't hardcode.
- The Streamer carries account activity including order IDs → same sensitivity class as positions. Anything we log from `ACCT_ACTIVITY` responses should strip PII (account number → hashed).
