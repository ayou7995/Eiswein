"""Trade import orchestration (Workstream C).

Two public operations:

* :meth:`TradeImportService.preview` — parses + cross-checks, writes
  NOTHING. Returns a :class:`PreviewResult` the UI renders as a
  color-coded table so the user can inspect what will happen before
  committing.
* :meth:`TradeImportService.apply` — re-parses (the HTTP handler
  re-passes a fresh :class:`io.BytesIO` over the same uploaded bytes)
  and persists each importable row through
  :class:`PositionRepository`. Each record is wrapped in a savepoint
  (``session.begin_nested``) so one poison row cannot nuke the whole
  import (rule 14: graceful degradation).

Idempotency
-----------
Dedup is belt-and-suspenders:

1. Before proposing a row, :meth:`preview` queries
   ``trade_repository.find_by_external_id`` and flags duplicates as
   ``skip_duplicate``.
2. On :meth:`apply`, we still attempt the insert and catch
   :class:`IntegrityError` — a concurrent import could race past the
   preview check. The partial unique index on
   ``(user_id, source, external_id)`` is the final backstop.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import IO, Literal

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.repositories.position_repository import (
    PositionRepository,
)
from app.db.repositories.trade_repository import TradeRepository
from app.ingestion.importers import IMPORTERS
from app.ingestion.importers.base import (
    BrokerImporter,
    ImportIssue,
    TradeImportRecord,
)

logger = structlog.get_logger("eiswein.services.trade_import")


PreviewAction = Literal["import", "skip_duplicate", "warn", "error"]


@dataclass(frozen=True)
class ImportSummary:
    """Counters returned in both preview and apply results."""

    would_import: int
    would_skip_duplicate: int
    warnings: int
    errors: int
    imported: int = 0
    skipped_duplicate: int = 0


@dataclass(frozen=True)
class PreviewRow:
    """One row's proposed disposition after parse + dedup + cross-check."""

    record: TradeImportRecord
    action: PreviewAction
    issues: list[ImportIssue]


@dataclass(frozen=True)
class PreviewResult:
    broker: str
    total_rows: int
    parsed: list[PreviewRow]
    file_issues: list[ImportIssue]
    summary: ImportSummary


@dataclass(frozen=True)
class ApplyResult:
    broker: str
    summary: ImportSummary
    issues: list[ImportIssue]


class UnknownBrokerError(ValueError):
    """Raised when ``broker_key`` is not registered in :data:`IMPORTERS`.

    The route layer translates this to HTTP 400 via a local wrapper;
    we do NOT subclass ``EisweinError`` here to keep the service layer
    free of HTTP concerns (rule 3: modular boundaries).
    """


class TradeImportService:
    def __init__(
        self,
        *,
        db: Session,
        trade_repository: TradeRepository,
        position_repository: PositionRepository,
    ) -> None:
        self._db = db
        self._trades = trade_repository
        self._positions = position_repository

    # --- Public operations ------------------------------------------------

    def preview(
        self,
        *,
        user_id: int,
        broker_key: str,
        file: IO[bytes],
    ) -> PreviewResult:
        """Parse + cross-check; read-only relative to Trade / Position."""
        importer = self._importer_for(broker_key)
        records, issues = importer.parse(file)

        file_issues = [i for i in issues if i.row_index == -1]
        row_issues_by_index = self._group_by_row([i for i in issues if i.row_index != -1])

        # Pair each record with the issues attached at its row. The
        # importer emits one issue per skipped row (options, zero qty,
        # bad number) — those rows never appear in ``records``. For
        # records that *did* parse, row-level issues only appear if the
        # importer added them defensively; today the Robinhood parser
        # does not, but the plumbing tolerates it.
        parsed: list[PreviewRow] = []
        for record in records:
            per_row = row_issues_by_index.get(self._row_key(record), [])
            duplicate = self._trades.find_by_external_id(
                user_id=user_id,
                source=record.source,
                external_id=record.external_id,
            )
            action: PreviewAction
            attached = list(per_row)
            if duplicate is not None:
                action = "skip_duplicate"
            else:
                cross_check_issues = self._cross_check(user_id=user_id, record=record)
                attached.extend(cross_check_issues)
                if any(issue.severity == "error" for issue in attached):
                    action = "error"
                elif any(issue.severity == "warn" for issue in attached):
                    # A warn-tagged but still-importable record. Today
                    # the parser only emits warnings for skipped rows
                    # (so they never reach here) — kept for future
                    # importers that may warn-but-import.
                    action = "warn"
                else:
                    action = "import"
            parsed.append(PreviewRow(record=record, action=action, issues=attached))

        summary = self._build_summary(parsed=parsed, file_issues=file_issues)
        # Total CSV rows ≈ records returned + row-level issues. File-
        # wide issues (row_index=-1) are counted separately.
        total_rows = len(records) + sum(1 for i in issues if i.row_index != -1)
        return PreviewResult(
            broker=broker_key,
            total_rows=total_rows,
            parsed=parsed,
            file_issues=file_issues,
            summary=summary,
        )

    def apply(
        self,
        *,
        user_id: int,
        broker_key: str,
        file: IO[bytes],
    ) -> ApplyResult:
        """Persist every importable row; count dedupes + survivors."""
        preview = self.preview(user_id=user_id, broker_key=broker_key, file=file)

        imported = 0
        skipped_duplicate = preview.summary.would_skip_duplicate
        carried_issues: list[ImportIssue] = list(preview.file_issues)
        for row in preview.parsed:
            carried_issues.extend(row.issues)
            if row.action != "import":
                continue
            try:
                self._apply_one(user_id=user_id, record=row.record)
                imported += 1
            except IntegrityError:
                # Concurrent-import race: the partial unique index
                # rejected the insert between preview() and apply().
                # Roll back the savepoint only — continue with the
                # rest of the file (rule 14).
                self._db.rollback()
                skipped_duplicate += 1
                logger.info(
                    "trade_import_duplicate_race",
                    broker=broker_key,
                )
            except Exception as exc:
                # Graceful per-row degradation (rule 14).
                self._db.rollback()
                carried_issues.append(
                    ImportIssue(
                        row_index=-1,
                        severity="error",
                        code="apply_failed",
                        message="匯入單筆交易失敗，已略過該筆",
                    )
                )
                logger.warning(
                    "trade_import_apply_failed",
                    broker=broker_key,
                    error_type=type(exc).__name__,
                )

        summary = ImportSummary(
            would_import=preview.summary.would_import,
            would_skip_duplicate=preview.summary.would_skip_duplicate,
            warnings=preview.summary.warnings,
            errors=preview.summary.errors,
            imported=imported,
            skipped_duplicate=skipped_duplicate,
        )
        return ApplyResult(
            broker=broker_key,
            summary=summary,
            issues=carried_issues,
        )

    # --- Internal helpers -------------------------------------------------

    def _importer_for(self, broker_key: str) -> BrokerImporter:
        importer = IMPORTERS.get(broker_key)
        if importer is None:
            raise UnknownBrokerError(broker_key)
        return importer

    def _row_key(self, record: TradeImportRecord) -> str:
        # Row-level issues in the current importer are keyed by row_index,
        # not record identity — this helper exists so future importers
        # can emit warn-but-keep issues attached to records via a shared
        # key (we compose it from external_id for stability).
        return record.external_id

    def _group_by_row(self, issues: list[ImportIssue]) -> dict[str, list[ImportIssue]]:
        grouped: dict[str, list[ImportIssue]] = {}
        for issue in issues:
            grouped.setdefault(str(issue.row_index), []).append(issue)
        return grouped

    def _cross_check(self, *, user_id: int, record: TradeImportRecord) -> list[ImportIssue]:
        """Catch sells that don't have a matching open position.

        We only flag sells. A buy without a prior position is valid —
        :meth:`apply` will auto-open one. A sell without a position
        can't possibly be right (we'd be creating a ghost negative
        position), so refuse at preview time.
        """
        issues: list[ImportIssue] = []
        if record.side == "sell":
            open_position = self._positions.get_open_for_symbol(
                user_id=user_id, symbol=record.symbol
            )
            if open_position is None:
                issues.append(
                    ImportIssue(
                        row_index=-1,
                        severity="error",
                        code="sell_without_position",
                        message=f"{record.symbol}：出售前無持有部位",
                    )
                )
        return issues

    def _apply_one(self, *, user_id: int, record: TradeImportRecord) -> None:
        """Insert one trade inside a savepoint.

        Raises on failure — the caller handles rollback + counting.
        """
        with self._db.begin_nested():
            if record.side == "buy":
                position = self._positions.get_open_for_symbol(
                    user_id=user_id, symbol=record.symbol
                )
                if position is None:
                    position = self._positions.create_open(
                        user_id=user_id,
                        symbol=record.symbol,
                        shares=record.shares,
                        avg_cost=record.price,
                        opened_at=record.executed_at,
                        notes=record.note,
                    )
                    realized = None
                else:
                    self._positions.apply_buy(position, shares=record.shares, price=record.price)
                    realized = None
            else:
                # Preview already guaranteed the open position exists;
                # re-check defensively — an intervening manual DELETE
                # could have closed it between preview and apply.
                position = self._positions.get_open_for_symbol(
                    user_id=user_id, symbol=record.symbol
                )
                if position is None:
                    msg = f"open position disappeared for {record.symbol}"
                    raise RuntimeError(msg)
                realized = self._positions.apply_sell(
                    position, shares=record.shares, price=record.price
                )

            self._trades.append(
                user_id=user_id,
                position_id=position.id,
                symbol=record.symbol,
                side=record.side,
                shares=record.shares,
                price=record.price,
                executed_at=record.executed_at,
                realized_pnl=realized,
                note=record.note,
                source=record.source,
                external_id=record.external_id,
            )

    def _build_summary(
        self,
        *,
        parsed: list[PreviewRow],
        file_issues: list[ImportIssue],
    ) -> ImportSummary:
        would_import = sum(1 for r in parsed if r.action == "import")
        would_skip_duplicate = sum(1 for r in parsed if r.action == "skip_duplicate")
        warnings = sum(1 for r in parsed if r.action == "warn")
        row_error_count = sum(1 for r in parsed if r.action == "error")
        # Count file-wide errors (severity=='error') toward the error
        # total so the UI surfaces a blocking banner on bad CSV.
        file_error_count = sum(1 for i in file_issues if i.severity == "error")
        file_warn_count = sum(1 for i in file_issues if i.severity == "warn")
        # Parser-emitted row-level warnings (e.g. options_skipped,
        # zero_quantity) aren't attached to records — count them by
        # inspecting the preview's total vs parsed length can't work
        # since the parser doesn't return them here. This summary
        # reflects only record-level dispositions; the API response
        # carries the full issue list so the UI can count however it
        # wants.
        return ImportSummary(
            would_import=would_import,
            would_skip_duplicate=would_skip_duplicate,
            warnings=warnings + file_warn_count,
            errors=row_error_count + file_error_count,
        )


__all__: tuple[str, ...] = (
    "ApplyResult",
    "ImportSummary",
    "PreviewAction",
    "PreviewResult",
    "PreviewRow",
    "TradeImportService",
    "UnknownBrokerError",
)
