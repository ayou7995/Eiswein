"""Centralized data ingestion — the ONLY layer that talks to DataSources.

Per CLAUDE.md Hard Operational Invariants:
* Indicators are pure functions — they never fetch over the network.
* ONE yfinance bulk call per daily_update.
* Per-symbol locks prevent concurrent cold-start fetches of the same
  ticker.

Two call sites:
* :func:`backfill.backfill_ticker` — cold start when a user adds a
  ticker to the watchlist.
* :func:`daily_ingestion.run_daily_update` — nightly scheduler job.
"""
