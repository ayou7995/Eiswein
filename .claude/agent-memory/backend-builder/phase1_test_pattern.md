---
name: FakeDataSource test pattern
description: How to test ingestion / API paths without mocking yfinance. Uses the FakeDataSource fixture from tests/conftest.py.
type: project
---

# FakeDataSource pattern

## Why

Mocking `yfinance.download` at the library level is brittle — if we refactor the adapter, tests break on implementation details rather than behavior. Mocking at the `DataSource` ABC is stable.

## Fixture location

`tests/conftest.py` exposes:
- `FakeDataSourceConfig(frames={}, empty_for=set(), error_for=set(), delay_seconds=0.0, health=DataSourceHealth(...))`
- `FakeDataSource(config)` — records every `bulk_download` call on `self.calls` as `(op, symbols_list, period)`
- `fake_data_source` fixture — zero-config default
- `make_price_frame(days, start_price)` — deterministic OHLCV generator

The `app` fixture preinjects `fake_data_source` onto `app.state.data_source`, so all API tests that use `client` fixture get the fake automatically.

## Testing cold-start timeout

```python
def test_cold_start_timeout(client, test_password, app):
    slow = FakeDataSource(FakeDataSourceConfig(delay_seconds=0.2))
    app.state.data_source = slow
    import app.api.v1.watchlist_routes as wr
    original = wr._COLD_START_BUDGET_SECONDS
    wr._COLD_START_BUDGET_SECONDS = 0.05
    try:
        resp = client.post("/api/v1/watchlist", json={"symbol": "SPY"})
    finally:
        wr._COLD_START_BUDGET_SECONDS = original
    assert resp.status_code == 202
```

## Testing daily_update

Monkeypatch the market calendar so tests pass on weekends:
```python
monkeypatch.setattr("app.ingestion.daily_ingestion.is_trading_day_et", lambda: True)
```

The `_reset_ingestion_locks` fixture is autouse — it clears the module-level lock registry between tests, avoiding cross-test contamination.
