"""Broker importer abstract base (Workstream C).

Contract
--------
``parse(file)`` returns a *tuple* ``(records, issues)``. Subclasses
must NEVER raise on parse errors — file-wide problems (bad CSV,
missing required columns, non-UTF-8 bytes) must be reported as a
single ``ImportIssue`` with ``row_index=-1`` and ``severity="error"``.
Raising breaks the service-layer contract that ``preview`` can always
present *something* to the user; a raised exception would become an
opaque 500 instead of a user-readable banner.

Records returned here are the post-filter set — options / non-trade
rows / zero-quantity rows are dropped and surfaced as ``ImportIssue``
entries alongside. The service layer treats the two lists as
independent: dedup/cross-check against the DB happens on the record
list; issues are carried through to the HTTP response verbatim.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import IO, Literal

TradeSide = Literal["buy", "sell"]


@dataclass(frozen=True)
class TradeImportRecord:
    """A single parsed trade row, ready to flow through PositionRepository.

    ``external_id`` is a broker-supplied (or deterministically-derived)
    identifier used for idempotent re-imports. The uniqueness guarantee
    is enforced at the DB layer by the partial unique index on
    ``(user_id, source, external_id)`` (migration 0008).
    """

    symbol: str
    side: TradeSide
    shares: Decimal
    price: Decimal
    executed_at: datetime
    external_id: str
    source: str
    note: str | None = None


@dataclass(frozen=True)
class ImportIssue:
    """Per-row or file-wide problem surfaced to the user.

    ``row_index`` is 1-based (row 0 is the CSV header). A value of
    ``-1`` means file-wide (e.g. malformed CSV, missing columns). The
    ``code`` is a stable machine string for UI conditionals; the
    ``message`` is Traditional Chinese for display.
    """

    row_index: int
    severity: Literal["warn", "error"]
    code: str
    message: str


class BrokerImporter(abc.ABC):
    """Each broker CSV format gets one importer instance.

    Implementations expose ``SOURCE_KEY`` — the value stored in
    ``Trade.source`` and used as the public broker identifier in the
    API (``POST /import/trades/preview?broker=robinhood``). For
    :class:`BrokerCsvImporter` the key is supplied at construction
    time so a single class can serve every Robinhood-shaped broker;
    a future broker with a custom format would override the property.
    """

    @property
    @abc.abstractmethod
    def SOURCE_KEY(self) -> str:
        """The broker identifier persisted to ``Trade.source``."""

    @abc.abstractmethod
    def parse(self, file: IO[bytes]) -> tuple[list[TradeImportRecord], list[ImportIssue]]:
        """Parse a file handle into records + issues.

        Implementations MUST NOT raise for parseable-but-invalid input;
        they emit ``ImportIssue`` rows instead. Raising is reserved
        for programming bugs (the service layer will bubble those as
        500s).
        """


__all__: tuple[str, ...] = (
    "BrokerImporter",
    "ImportIssue",
    "TradeImportRecord",
    "TradeSide",
)
