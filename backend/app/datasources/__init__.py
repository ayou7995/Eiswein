"""Data source abstraction + provider implementations.

`DataSource` is the infrastructure boundary indicator code talks to.
Provider implementations (yfinance, FRED, schwab, polygon) live under
this package; the factory in ``factory.py`` wires the right one based
on ``settings.data_source_provider``.

Indicators NEVER import from this package directly — they receive
DataFrames from the ingestion layer (see Hard Operational Invariants in
CLAUDE.md).
"""

from app.datasources.base import DataSource, DataSourceHealth

__all__ = ("DataSource", "DataSourceHealth")
