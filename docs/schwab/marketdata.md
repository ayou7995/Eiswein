# Schwab Market Data REST API

**Source**: Schwab Developer Portal → Market Data Production → Specifications
**Captured**: 2026-04-20 (endpoints added incrementally)
**Status**: reference only — `datasources/schwab_source.py` is a stub.

Base URL: `https://api.schwabapi.com/marketdata/v1`
Auth: Bearer token in `Authorization: Bearer <access_token>` header. See `docs/schwab/oauth.md` (pending).

---

## Endpoints available (from portal)

| Group | Path | Eiswein use | Documented below |
|---|---|---|---|
| **Quotes** | `GET /quotes`, `GET /{symbol_id}/quotes` | Real-time / delayed snapshots | ✅ below |
| **PriceHistory** | `GET /pricehistory` | **Daily OHLCV backfill + update** | ✅ below |
| Option Chains | `GET /chains` | — (we don't trade options) | — |
| Option Expiration Chain | `GET /expirationchain` | — | — |
| Movers | `GET /movers/{symbol_id}` | — | — |
| **MarketHours** | `GET /markets`, `GET /markets/{market_id}` | Optional — replace `market_calendar.py` | ✅ below |
| **Instruments** | `GET /instruments`, `GET /instruments/{cusip_id}` | Optional — symbol / CUSIP lookup | ✅ below |

---

## GET /pricehistory

Historical OHLCV candles for a single symbol and date range. Frequency available depends on `periodType`. The `datetime` field in candles is **epoch milliseconds**.

### Request

`GET https://api.schwabapi.com/marketdata/v1/pricehistory`

### Query parameters

| Name | Type | Required | Description |
|---|---|---|---|
| `symbol` | string | **yes** | Equity symbol. Example: `AAPL`. |
| `periodType` | string | no | Chart period unit. Allowed: `day`, `month`, `year`, `ytd`. |
| `period` | int32 | no | Number of `periodType` units. Valid-value matrix below. |
| `frequencyType` | string | no | Candle granularity. Allowed: `minute`, `daily`, `weekly`, `monthly`. Depends on `periodType`. |
| `frequency` | int32 | no | Duration of each candle. Depends on `frequencyType`. Default `1`. |
| `startDate` | int64 | no | Epoch **ms**. If omitted, computed as `endDate - period` (skips weekends/holidays). |
| `endDate` | int64 | no | Epoch **ms**. Default: market close of previous business day. |
| `needExtendedHoursData` | bool | no | Include pre/post-market bars. |
| `needPreviousClose` | bool | no | Return `previousClose` + `previousCloseDate` in response. |

#### `period` valid values (by `periodType`)

| `periodType` | valid `period` values | default (if period omitted) |
|---|---|---|
| `day` | 1, 2, 3, 4, 5, 10 | 10 |
| `month` | 1, 2, 3, 6 | 1 |
| `year` | 1, 2, 3, 5, 10, 15, 20 | 1 |
| `ytd` | 1 | 1 |

#### `frequencyType` valid values (by `periodType`)

| `periodType` | valid `frequencyType` | default (if frequencyType omitted) |
|---|---|---|
| `day` | `minute` | `minute` |
| `month` | `daily`, `weekly` | `weekly` |
| `year` | `daily`, `weekly`, `monthly` | `monthly` |
| `ytd` | `daily`, `weekly` | `weekly` |

#### `frequency` valid values (by `frequencyType`)

| `frequencyType` | valid `frequency` values |
|---|---|
| `minute` | 1, 5, 10, 15, 30 |
| `daily` | 1 |
| `weekly` | 1 |
| `monthly` | 1 |

### Response 200 — candles for date range

```json
{
  "symbol": "AAPL",
  "empty": false,
  "previousClose": 174.56,
  "previousCloseDate": 1639029600000,
  "candles": [
    {
      "open": 175.01,
      "high": 175.15,
      "low": 175.01,
      "close": 175.04,
      "volume": 10719,
      "datetime": 1639137600000
    }
  ]
}
```

| Field | Type | Notes |
|---|---|---|
| `symbol` | string | Echo of request. |
| `empty` | bool | `true` = no data in range (not an error). Adapter should surface as empty DataFrame. |
| `previousClose` | number | Only present when `needPreviousClose=true`. |
| `previousCloseDate` | int64 | Epoch **ms**. |
| `candles[]` | array | Empty array possible if `empty=true`. |
| `candles[].open/high/low/close` | number | OHLC. |
| `candles[].volume` | int64 | Share count. |
| `candles[].datetime` | int64 | Epoch **ms**. Convert to `date` for Eiswein's `DailyPrice` table. |

### Response 400 — Bad Request

```json
{
  "errors": [
    {
      "id": "6808262e-52bb-4421-9d31-6c0e762e7dd5",
      "status": "400",
      "title": "Bad Request",
      "detail": "Missing header",
      "source": { "header": "Authorization" }
    }
  ]
}
```

`source` variants:
- `{ "header": "..." }` — missing/invalid header.
- `{ "parameter": "..." }` — invalid query param (e.g. `fields`).
- `{ "pointer": ["/data/attributes/..."] }` — invalid body field (for POST-style endpoints, not this GET).

### Response 401 — Unauthorized

```json
{ "errors": [{ "status": 401, "title": "Unauthorized", "id": "<guid>" }] }
```

Usually means access token expired. Client should refresh token and retry once.

### Response 404 — Not Found

```json
{ "errors": [{ "status": 404, "title": "Not Found", "id": "<guid>" }] }
```

Symbol not found / delisted. Eiswein's existing `data_status: "delisted"` handling on Watchlist applies.

### Response 500 — Internal Server Error

```json
{ "errors": [{ "id": "<guid>", "status": 500, "title": "Internal Server Error" }] }
```

Retry with exponential backoff (existing `tenacity` pattern in `ingestion/daily_ingestion.py`).

### Response headers (all responses)

| Header | Example | Use |
|---|---|---|
| `Schwab-Client-CorrelId` | `977dbd7f-992e-44d2-a5f4-e213d29c8691` | Per-request GUID. Log this alongside our `request_id` for Schwab support tickets. |
| `Schwab-Resource-Version` | `1` | API version echoed back. |

---

## GET /quotes

Snapshot quote for one or many symbols (up to many dozens per call). Different asset types share the same envelope but have different sub-objects inside `quote` and `reference`. Bid/ask may be absent for index-type symbols.

### Request

`GET https://api.schwabapi.com/marketdata/v1/quotes`

### Query parameters

| Name | Type | Required | Description |
|---|---|---|---|
| `symbols` | string | **yes** | Comma-separated list of symbols. Mix of asset types OK. Example: `MRAD,EATOF,EBIZ,AAPL,BAC,$DJI,$SPX,AMZN 230317C01360000,/ESH23,AUD/CAD`. |
| `fields` | string | no | Subset of root nodes to return. Allowed: `all`, `quote`, `fundamental`, `extended`, `reference`, `regular`. Comma-separated. Default: `all`. Omit for full response. |
| `indicative` | bool | no | If `true`, ETF symbols also get their indicative quote (`$ABC.IV`). Default `false`. |

### Response 200 — object keyed by symbol

The response is a **map**, not an array: `{ "AAPL": {...}, "BAC": {...} }`.

Each symbol entry has:

| Field | Type | Notes |
|---|---|---|
| `assetMainType` | string | `EQUITY`, `MUTUAL_FUND`, `INDEX`, `OPTION`, `FUTURE`, `FOREX`. |
| `assetSubType` | string | `ETF`, `ADR`, etc. Only on EQUITY. |
| `symbol` | string | Echo of request. |
| `quoteType` | string | `NBBO` for consolidated top-of-book. |
| `realtime` | bool | `true` = real-time; `false` = delayed (usually 15 min). |
| `ssid` | int | Schwab internal security ID. Store for later lookups. |
| `reference` | object | Identification: `cusip`, `description`, `exchange` (1-char code), `exchangeName`. EQUITY includes `otcMarketTier` when applicable. OPTION adds `strikePrice`, `expirationMonth`, `expirationDay`, `expirationYear`, `daysToExpiration`, `underlying`, etc. FUTURE adds `futureExpirationDate`, `futureMultiplier`, `futureSettlementPrice`, etc. |
| `quote` | object | Per-asset-type price data — see subsection below. |
| `regular` | object | Regular-market-hours subset (EQUITY only). |
| `fundamental` | object | `eps`, `peRatio`, `divAmount`, `divYield`, `avg10DaysVolume`, `avg1YearVolume`, dividend dates. EQUITY/ETF/MUTUAL_FUND only. |

Exchange codes (1-char): `Q` = NASDAQ, `N` = NYSE, `P` = NYSE Arca, `A` = AMEX, `3` = Mutual Fund, `9` = OTC Markets, `u` = Nasdaq OTCBB, `0` = Index.

#### `quote` subset — EQUITY / ETF (the only types Eiswein will consume)

```json
{
  "52WeekHigh": 169,
  "52WeekLow": 1.1,
  "askMICId": "MEMX",
  "askPrice": 168.41,
  "askSize": 400,
  "askTime": 1644854683672,
  "bidMICId": "IEGX",
  "bidPrice": 168.40,
  "bidSize": 400,
  "bidTime": 1644854683633,
  "closePrice": 177.57,
  "highPrice": 169,
  "lastMICId": "XADF",
  "lastPrice": 168.405,
  "lastSize": 200,
  "lowPrice": 167.09,
  "mark": 168.405,
  "markChange": -9.165,
  "markPercentChange": -5.1613,
  "netChange": -9.165,
  "netPercentChange": -5.1613,
  "openPrice": 167.37,
  "quoteTime": 1644854683672,
  "securityStatus": "Normal",
  "totalVolume": 22361159,
  "tradeTime": 1644854683408,
  "volatility": 0.0347
}
```

All timestamps are **epoch milliseconds**. `securityStatus` ∈ `"Normal"`, `"Halted"`, `"Closed"`, `"Unknown"`.

#### `quote` subset — INDEX (e.g. `$SPX`, `$DJI`)

No bid/ask (indices don't have a book). Has `closePrice`, `highPrice`, `lastPrice`, `lowPrice`, `openPrice`, `netChange`, `netPercentChange`, `totalVolume`, `tradeTime`, `securityStatus`. `securityStatus` is typically `"Unknown"` for indices.

#### `quote` subset — OPTION, FUTURE, FOREX, MUTUAL_FUND

Irrelevant for Eiswein (we only watch equities, ETFs, indices). Full examples are in the raw Schwab doc if ever needed.

### Response 400 / 401 / 500

Same JSON:API-ish envelope as `/pricehistory` (see above). `source` values for 400:
- `{ "header": "Authorization" }` — missing header.
- `{ "pointer": ["/data/attributes/symbols", "/data/attributes/cusips", "/data/attributes/ssids"] }` — no identifier provided.
- `{ "parameter": "fields" }` — invalid `fields` value. Valid values echoed back: `all, fundamental, reference, extended, quote, regular`.

### Response headers

| Header | Use |
|---|---|
| `Schwab-Client-CorrelId` | Log alongside request_id for support tickets. |

---

## GET /{symbol_id}/quotes

Single-symbol variant. Same response shape as `/quotes` (the map has one key). **Prefer `/quotes?symbols=X` in Eiswein** for a uniform response shape — use this only when the symbol happens to be in a URL path segment already.

### Request

`GET https://api.schwabapi.com/marketdata/v1/{symbol_id}/quotes`

### Parameters

| Name | Type | In | Required | Description |
|---|---|---|---|---|
| `symbol_id` | string | path | **yes** | Symbol, e.g. `TSLA`. |
| `fields` | string | query | no | Same as `/quotes`. Default `all`. |

### Responses

Same shapes as `/quotes` (200, 400, 401, 404, 500). 404 only appears on this endpoint when the symbol isn't found — the bulk `/quotes` just omits unknown symbols from the response map.

---

## GET /markets

Trading hours across markets for a single date. Default date is today; can query up to 1 year forward. Authoritative source for "is the US equity market open today?" — potential replacement for our own `market_calendar.py`.

### Request

`GET https://api.schwabapi.com/marketdata/v1/markets`

### Query parameters

| Name | Type | Required | Description |
|---|---|---|---|
| `markets` | array[string] | **yes** | One or more of `equity`, `option`, `bond`, `future`, `forex`. Schwab's Swagger shows it as `array[string]`; on the wire it's comma-separated (`markets=equity,option`). |
| `date` | string ($date) | no | Date in `YYYY-MM-DD`. Valid range: today → today+1y. Defaults to today. |

### Response 200

Nested map: `{ <market>: { <product>: {...} } }`.

```json
{
  "equity": {
    "EQ": {
      "date": "2022-04-14",
      "marketType": "EQUITY",
      "product": "EQ",
      "productName": "equity",
      "isOpen": true,
      "sessionHours": {
        "preMarket":     [{ "start": "...T07:00:00-04:00", "end": "...T09:30:00-04:00" }],
        "regularMarket": [{ "start": "...T09:30:00-04:00", "end": "...T16:00:00-04:00" }],
        "postMarket":    [{ "start": "...T16:00:00-04:00", "end": "...T20:00:00-04:00" }]
      }
    }
  },
  "option": {
    "EQO": { "marketType": "OPTION", "product": "EQO", "productName": "equity option", "isOpen": true, "sessionHours": { "regularMarket": [...] } },
    "IND": { "marketType": "OPTION", "product": "IND", "productName": "index option", "isOpen": true, "sessionHours": { "regularMarket": [...] } }
  }
}
```

| Field | Type | Notes |
|---|---|---|
| `<market>` | object | Key is the market name (`equity`, `option`, ...). |
| `<market>.<product>` | object | Key is the product code. EQUITY → `EQ`. OPTION → `EQO` (equity option) / `IND` (index option). |
| `.date` | string | `YYYY-MM-DD`. |
| `.marketType` | string | `EQUITY`, `OPTION`, `BOND`, `FUTURE`, `FOREX`. |
| `.isOpen` | bool | **The one Eiswein cares about.** `false` on weekends + holidays. |
| `.sessionHours.preMarket[]` | array | Pre-market windows. Only present when applicable. |
| `.sessionHours.regularMarket[]` | array | Regular session windows. Empty array (or missing `sessionHours` entirely) when the market is fully closed. |
| `.sessionHours.postMarket[]` | array | Post-market windows. |
| `.sessionHours.*.start/end` | string | ISO-8601 with tz offset (`2022-04-14T09:30:00-04:00`). |

### Response 400 / 401 / 500

Same JSON:API-ish envelope as `/pricehistory` / `/quotes`.

### Response headers

`Schwab-Client-CorrelId`.

---

## GET /markets/{market_id}

Single-market variant. Response shape identical to `/markets` except:
- The top level contains only one market key.
- Each product adds two extra fields: `exchange` and `category` (usually `"NULL"` — reserved).

### Request

`GET https://api.schwabapi.com/marketdata/v1/markets/{market_id}`

### Parameters

| Name | Type | In | Required | Description |
|---|---|---|---|---|
| `market_id` | string | path | **yes** | `equity`, `option`, `bond`, `future`, `forex`. |
| `date` | string ($date) | query | no | Same as `/markets`. |

### Response 200

```json
{
  "equity": {
    "EQ": {
      "date": "2022-04-14",
      "marketType": "EQUITY",
      "exchange": "NULL",
      "category": "NULL",
      "product": "EQ",
      "productName": "equity",
      "isOpen": true,
      "sessionHours": { "preMarket": [...], "regularMarket": [...], "postMarket": [...] }
    }
  }
}
```

Errors: 400, 401, **404** (path version only — when `market_id` isn't recognized), 500.

---

## Eiswein-specific recipes

These are the exact param sets we'll use if Schwab replaces yfinance in `daily_ingestion.py`.

### Recipe 1 — Cold-start backfill (2 years of daily bars)

```
GET /pricehistory
  ?symbol=SPY
  &periodType=year
  &period=2
  &frequencyType=daily
  &frequency=1
  &needPreviousClose=true
```

→ Used once per newly-added watchlist symbol. Mirrors existing `backfill.py` behavior.

### Recipe 2 — Daily incremental update

```
GET /pricehistory
  ?symbol=SPY
  &periodType=day
  &period=5
  &frequencyType=daily
  &frequency=1
```

`period=5` instead of `1` so we naturally cover weekends and a one-day outage; the UPSERT on `DailyPrice` makes this idempotent.

### Recipe — Watchlist snapshot refresh (single call for N tickers)

```
GET /quotes
  ?symbols=SPY,QQQ,IWM,AAPL,MSFT
  &fields=quote,reference
```

→ Use for the intraday `current_price` field on `/api/v1/positions` and `/api/v1/ticker/{symbol}/status`. One request returns all watchlist quotes; map the response by symbol directly into our existing Pydantic wire shape. Trim `fields` to `quote,reference` to skip fundamental/extended (saves bytes).

### Recipe — Single-symbol lookup

Prefer `/quotes?symbols=X&fields=quote,reference` over `/{X}/quotes` so the response shape (`{ "X": {...} }`) is always a map. Reduces adapter branches.

### Recipe — Market-open check before daily_update

```
GET /markets/equity?date=2026-04-20
```

→ Used by the scheduled `daily_update` job to skip weekends/holidays. Parse `response.equity.EQ.isOpen`. Equivalent to our existing `market_calendar.is_trading_day()`; if we trust Schwab, we can drop the `pandas_market_calendars` dependency.

### Recipe — Session-end timing for post-close ingestion

```
GET /markets/equity  # no date param = today
```

→ Read `response.equity.EQ.sessionHours.regularMarket[0].end`. Use this as the authoritative "after this, daily bars are final" timestamp. Saves us hard-coding 16:00 ET in `daily_ingestion.py`.

### Recipe 3 — Intraday 5-min bars (Phase S4, future)

```
GET /pricehistory
  ?symbol=SPY
  &periodType=day
  &period=1
  &frequencyType=minute
  &frequency=5
```

For intra-day stop-loss monitoring. Would be called by `jobs/intra_day_stop_loss.py` (planned, not built).

---

## Mapping into Eiswein's adapter

Planned shape of `datasources/schwab_source.py::SchwabDataSource`:

```python
async def get_daily_ohlcv(symbol: str, *, start: date, end: date) -> pd.DataFrame:
    end_ms = _to_epoch_ms(end)
    start_ms = _to_epoch_ms(start)
    payload = await _get(
        "/pricehistory",
        params={
            "symbol": symbol,
            "periodType": "day",
            "frequencyType": "daily",
            "frequency": 1,
            "startDate": start_ms,
            "endDate": end_ms,
        },
    )
    if payload["empty"]:
        return pd.DataFrame(columns=["date","open","high","low","close","volume"])
    return _candles_to_frame(payload["candles"])
```

`_candles_to_frame` converts `datetime` (ms epoch) → `date`, preserves `open/high/low/close/volume`. Output shape matches yfinance adapter so the rest of `ingestion/` doesn't change.

---

## GET /instruments

**Purpose**: "Get Instruments details by using different projections. Get more specific fundamental instrument data by using `fundamental` as the projection."

Used for symbol / CUSIP lookup, fuzzy symbol search, and (with `projection=fundamental`) basic fundamental fields like shares outstanding, dividends, ratios.

### Request

`GET https://api.schwabapi.com/marketdata/v1/instruments`

### Query Parameters

| Name | Type | Required | Description |
|---|---|---|---|
| `symbol` | string | **yes** | Symbol(s) of a security. Multiple symbols supported via comma-separated list: `symbol=AAPL,BAC`. |
| `projection` | string | **yes** | Search type. Enum: `symbol-search`, `symbol-regex`, `desc-search`, `desc-regex`, `search`, `fundamental`. |

**Projection semantics** (inferred from name + Schwab docs convention):
- `symbol-search` — exact symbol match (e.g., `AAPL` → Apple)
- `symbol-regex` — regex against symbol (e.g., `AA.*`)
- `desc-search` — word match against description (e.g., `bank` → all bank stocks)
- `desc-regex` — regex against description
- `search` — combined symbol + description
- `fundamental` — return fundamental data (ratios, dividends, etc.) — payload is richer

### Response `200 application/json`

```json
{
  "instruments": [
    {
      "cusip": "037833100",
      "symbol": "AAPL",
      "description": "Apple Inc",
      "exchange": "NASDAQ",
      "assetType": "EQUITY"
    },
    {
      "cusip": "060505104",
      "symbol": "BAC",
      "description": "Bank Of America Corp",
      "exchange": "NYSE",
      "assetType": "EQUITY"
    }
  ]
}
```

With `projection=fundamental`, each object has an additional `fundamental` sub-object (not documented in this Swagger page — see Schwab's full reference when needed).

**Instrument fields**
| Field | Type | Note |
|---|---|---|
| `cusip` | string | 9-char CUSIP. |
| `symbol` | string | Trading symbol. |
| `description` | string | Company / security name. |
| `exchange` | string | `NASDAQ`, `NYSE`, `AMEX`, `PACIFIC`, etc. |
| `assetType` | string | `EQUITY`, `ETF`, `MUTUAL_FUND`, `FIXED_INCOME`, `INDEX`, `CASH_EQUIVALENT`, `OPTION`, `CURRENCY`. |

### Response headers

| Header | Type | Note |
|---|---|---|
| `Schwab-Client-CorrelId` | string (GUID) | Unique per operation. Include in support tickets. |
| `Schwab-Resource-Version` | integer | API version served (e.g., `3`). |

### Status codes + error shape

Market Data uses a **JSON:API-style** error envelope (different from Trader API's `{message, errors[]}`):

```json
{
  "errors": [
    {
      "id": "6808262e-52bb-4421-9d31-6c0e762e7dd5",
      "status": "400",
      "title": "Bad Request",
      "detail": "Missing header",
      "source": {
        "header": "Authorization"
      }
    }
  ]
}
```

`source` is one of:
- `{"header": "..."}` — missing / invalid header
- `{"parameter": "..."}` — bad query param
- `{"pointer": ["..."]}` — bad body field (JSON Pointer style)

| Code | Meaning |
|---|---|
| `200` | OK |
| `400` | Generic client error (validation, combination rules) |
| `401` | Missing / invalid access token |
| `404` | Instrument not found |
| `500` | Internal server error |

**Common 400 triggers** (from Swagger example):
- `Missing header` on `Authorization`
- `Search combination should have min of 1` — at least one of `symbols`, `cusips`, `ssids` required
- `fields` param must be one of `all`, `fundamental`, `reference`, `extended`, `quote`, `regular`, or empty

> The error schema references `symbols`, `cusips`, `ssids`, and a `fields` param — none of these appear in the documented public query params. They likely belong to the portal's "Try it out" JSON:API body variant or a batch endpoint that isn't part of the public GET surface. For Eiswein, stick to `symbol` + `projection` on GET.

### Eiswein usage

- **Phase S2** (optional): When the user adds a ticker to the watchlist, call `/instruments?symbol=AAPL&projection=symbol-search` to resolve CUSIP + official exchange + description. Store on the watchlist row. Backup path: yfinance's `Ticker.info` already gives us `longName`, so this endpoint is nice-to-have, not required.
- **Phase S3** (reconciliation): Map `ACCT_ACTIVITY` payloads — which sometimes arrive with CUSIP but not symbol — to symbol via `/instruments/{cusip}`. See `streamer.md` §5.
- **Not for fundamentals**: yfinance is the primary fundamentals source for Eiswein. This endpoint's `projection=fundamental` is reference-only.

---

## GET /instruments/{cusip_id}

**Purpose**: "Get basic instrument details by cusip."

### Request

`GET https://api.schwabapi.com/marketdata/v1/instruments/{cusip_id}`

### Path Parameters

| Name | Type | Required | Description |
|---|---|---|---|
| `cusip_id` | string | **yes** | CUSIP of the security (9-char). |

### Response `200 application/json`

Single instrument object (no `{"instruments": [...]}` wrapper):

```json
{
  "cusip": "037833100",
  "symbol": "AAPL",
  "description": "Apple Inc",
  "exchange": "NASDAQ",
  "assetType": "EQUITY"
}
```

### Response headers + error shape

Same as `GET /instruments`. Status codes: `200` / `400` / `401` / `404` / `500`.

### Eiswein usage

- Phase S3 CUSIP → symbol resolution for Streamer `ACCT_ACTIVITY` payloads that include CUSIP without symbol.
- Otherwise the list endpoint is more flexible; this one is only useful when CUSIP is the only identifier we have.

---

## Pending

All core Market Data endpoints Eiswein cares about are now documented. Remaining (explicitly skipped for scope):
- `GET /chains`, `GET /expirationchain` — options (not traded).
- `GET /movers/{symbol_id}` — gainers/losers screens (not used).
