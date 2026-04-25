"""Broker trade CSV importers (Workstream C).

Importers parse a broker's account-statement export into a uniform
``TradeImportRecord`` list + an ``ImportIssue`` list. They do NOT
touch the database — the service layer
(:mod:`app.services.trade_import_service`) owns dedup + persistence.

The same :class:`BrokerCsvImporter` powers every supported broker.
:data:`SUPPORTED_BROKERS` is the canonical list (key + display label)
the API exposes via ``GET /api/v1/import/brokers``; the frontend uses
that endpoint as its source of truth so the dropdown stays in sync.

Adding a new broker = appending a tuple to :data:`SUPPORTED_BROKERS`.
The shared parser handles every Robinhood-style column layout. A
broker with a meaningfully different format would still get its own
:class:`BrokerImporter` subclass and a custom registry entry.
"""

from __future__ import annotations

from app.ingestion.importers.base import BrokerImporter, ImportIssue, TradeImportRecord
from app.ingestion.importers.broker_csv import BrokerCsvImporter

# (broker_key, display label). Display labels are intentionally English —
# they're proper nouns / brand names and rendering them in zh-TW would
# create false-translation noise. The key is lowercase ASCII so it can
# round-trip through HTTP form fields and SQL columns without escaping.
SUPPORTED_BROKERS: tuple[tuple[str, str], ...] = (
    ("robinhood", "Robinhood"),
    ("moomoo", "moomoo"),
    ("schwab", "Charles Schwab"),
    ("fidelity", "Fidelity"),
    ("etrade", "E*TRADE"),
    ("tdameritrade", "TD Ameritrade"),
    ("chase", "Chase (J.P. Morgan)"),
    ("ibkr", "Interactive Brokers"),
    ("vanguard", "Vanguard"),
    ("webull", "Webull"),
    ("merrill", "Merrill Edge"),
    ("sofi", "SoFi Active Invest"),
    ("public", "Public"),
    ("other", "Other"),
)

IMPORTERS: dict[str, BrokerImporter] = {
    key: BrokerCsvImporter(source_key=key) for key, _label in SUPPORTED_BROKERS
}

__all__: tuple[str, ...] = (
    "IMPORTERS",
    "SUPPORTED_BROKERS",
    "BrokerCsvImporter",
    "BrokerImporter",
    "ImportIssue",
    "TradeImportRecord",
)
