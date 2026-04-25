"""Generic broker CSV importer (Workstream C).

Originally written for Robinhood, but the column contract
(``Activity Date / Process Date / Settle Date / Instrument /
Description / Trans Code / Quantity / Price / Amount``) is the
informal standard used by every broker statement we ship for in
v1 — Schwab, Fidelity, E*TRADE, Chase, Interactive Brokers, etc.

To support a new broker we register a new ``broker_key`` in
:mod:`app.ingestion.importers.__init__` and reuse this same parser.
The user picks a broker in the upload dialog; that key flows through
as ``Trade.source`` and as the prefix in the deterministic
``external_id`` hash so trades from different brokers can never collide
on dedup even if quantities and prices line up by coincidence.

Filtering rules
---------------
* Only ``Trans Code ∈ {Buy, Sell}`` rows become records. Routine
  corporate-action / cash-flow codes (``ACH``, ``DIV``, ``GOLD``,
  ``INT``, ``REC``, ``TAX``, ``CONV``, ``SLIP``, ``CDIV``, ``GDBP``...)
  are silently skipped.
* Options rows (``Instrument`` contains a space, or the symbol fails
  the equity-ticker regex like ``AAPL`` / ``BRK.B``) are skipped with
  a warning. Warrants like ``OXY+`` and escrow symbols like
  ``MEHCQ^`` also fail the regex and are skipped.
* Zero-quantity rows are skipped with a warning.
* Malformed money / date fields are skipped with an ``error``.

Idempotency
-----------
The CSV usually has no order ID, so the external_id is a SHA-256
prefix over ``broker_key | date | symbol | trans_code | quantity |
price``. That combination is unique in practice (two trades of
identical size at identical price on the same day in the same
brokerage is vanishingly rare; if it does happen, dedup is the
conservative choice).
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import IO, Final
from zoneinfo import ZoneInfo

from app.ingestion.importers.base import (
    BrokerImporter,
    ImportIssue,
    TradeImportRecord,
    TradeSide,
)

_REQUIRED_COLUMNS: Final[tuple[str, ...]] = (
    "Activity Date",
    "Instrument",
    "Trans Code",
    "Quantity",
    "Price",
)

# Stock tickers: 1-5 uppercase letters, optional single-letter suffix
# (class shares like BRK.B). Options contracts carry an expiry / strike
# encoded with spaces (e.g. "AAPL 12/20/2024 Call 180"); those fail
# this regex AND usually carry a space. Warrants ("OXY+") and escrow
# residues ("MEHCQ^") fail because of their non-letter suffix.
_EQUITY_SYMBOL_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Z]{1,5}(\.[A-Z])?$")

_DATE_FORMATS: Final[tuple[str, ...]] = (
    "%m/%d/%Y",
    "%Y-%m-%d",
    "%m/%d/%y",
)

_NY_TZ: Final[ZoneInfo] = ZoneInfo("America/New_York")
_UTC_TZ: Final[ZoneInfo] = ZoneInfo("UTC")

_TRADE_CODES: Final[dict[str, TradeSide]] = {"Buy": "buy", "Sell": "sell"}


def _parse_money(raw: str) -> Decimal:
    """Parse broker money strings into Decimal.

    Brokers format money as ``$1,234.56``; negatives as ``($1,234.56)``.
    Strip ``$``, ``,``, and parentheses; wrap parenthesised values in a
    leading ``-``. ``Decimal`` only — never float.
    """
    cleaned = raw.strip()
    if not cleaned:
        msg = "empty money value"
        raise InvalidOperation(msg)
    negative = cleaned.startswith("(") and cleaned.endswith(")")
    if negative:
        cleaned = cleaned[1:-1]
    cleaned = cleaned.replace("$", "").replace(",", "").strip()
    if not cleaned:
        msg = "empty money value after stripping"
        raise InvalidOperation(msg)
    value = Decimal(cleaned)
    return -value if negative else value


def _parse_date(raw: str) -> datetime:
    """Parse broker activity-date string into a UTC-aware datetime.

    Broker statements use America/New_York without a time component.
    Anchor at midnight ET and convert to UTC so storage is consistent
    with the rest of the system (Trade.executed_at is tz-aware UTC).
    """
    cleaned = raw.strip()
    if not cleaned:
        msg = "empty date"
        raise ValueError(msg)
    last_err: Exception | None = None
    for fmt in _DATE_FORMATS:
        try:
            naive = datetime.strptime(cleaned, fmt)
        except ValueError as exc:
            last_err = exc
            continue
        localized = naive.replace(tzinfo=_NY_TZ)
        return localized.astimezone(_UTC_TZ)
    raise ValueError(f"unparseable date: {cleaned!r}") from last_err


def _external_id(
    *,
    broker_key: str,
    activity_date: str,
    symbol: str,
    trans_code: str,
    quantity_raw: str,
    price_raw: str,
) -> str:
    # Use the raw (pre-parse) strings so two runs of the SAME file
    # produce identical hashes regardless of whether Decimal rounding
    # or date reformatting changes in the future. Broker prefix scopes
    # the namespace so an identical-looking row from two different
    # brokers does not collide on dedup.
    key = f"{broker_key}|{activity_date}|{symbol}|{trans_code}|{quantity_raw}|{price_raw}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]


class BrokerCsvImporter(BrokerImporter):
    """Parses the Robinhood-shaped column convention used by most brokers.

    ``source_key`` is the broker identifier persisted into ``Trade.source``
    and used as the dedup namespace prefix. The same parser handles every
    registered broker; the per-broker label is the only thing that varies
    between instances.
    """

    def __init__(self, source_key: str) -> None:
        if not source_key or not source_key.strip():
            msg = "source_key must be a non-empty string"
            raise ValueError(msg)
        self._source_key = source_key.strip()

    @property
    def SOURCE_KEY(self) -> str:
        return self._source_key

    def parse(self, file: IO[bytes]) -> tuple[list[TradeImportRecord], list[ImportIssue]]:
        records: list[TradeImportRecord] = []
        issues: list[ImportIssue] = []

        try:
            raw_bytes = file.read()
        except OSError as exc:
            issues.append(
                ImportIssue(
                    row_index=-1,
                    severity="error",
                    code="read_failed",
                    message=f"讀取檔案失敗：{exc}",
                )
            )
            return records, issues

        if not raw_bytes:
            issues.append(
                ImportIssue(
                    row_index=-1,
                    severity="error",
                    code="empty_file",
                    message="檔案為空",
                )
            )
            return records, issues

        try:
            text = raw_bytes.decode("utf-8-sig")
        except UnicodeDecodeError:
            issues.append(
                ImportIssue(
                    row_index=-1,
                    severity="error",
                    code="bad_encoding",
                    message="檔案必須是 UTF-8 編碼",
                )
            )
            return records, issues

        reader = csv.DictReader(io.StringIO(text))
        fieldnames = reader.fieldnames or []
        missing = [c for c in _REQUIRED_COLUMNS if c not in fieldnames]
        if missing:
            issues.append(
                ImportIssue(
                    row_index=-1,
                    severity="error",
                    code="missing_columns",
                    message=f"CSV 缺少必要欄位：{', '.join(missing)}",
                )
            )
            return records, issues

        try:
            for row_index, row in enumerate(reader, start=1):
                self._parse_row(row, row_index, records, issues)
        except csv.Error as exc:
            issues.append(
                ImportIssue(
                    row_index=-1,
                    severity="error",
                    code="malformed_csv",
                    message=f"CSV 格式錯誤：{exc}",
                )
            )
            return records, issues

        return records, issues

    def _parse_row(
        self,
        row: dict[str, str | None],
        row_index: int,
        records: list[TradeImportRecord],
        issues: list[ImportIssue],
    ) -> None:
        trans_code = (row.get("Trans Code") or "").strip()
        side = _TRADE_CODES.get(trans_code)
        if side is None:
            return

        instrument_raw = (row.get("Instrument") or "").strip()
        if (
            not instrument_raw
            or " " in instrument_raw
            or not _EQUITY_SYMBOL_RE.match(instrument_raw)
        ):
            issues.append(
                ImportIssue(
                    row_index=row_index,
                    severity="warn",
                    code="options_skipped",
                    message=f"第 {row_index} 列：選擇權或非股票商品，已略過",
                )
            )
            return
        symbol = instrument_raw.upper()

        quantity_raw = (row.get("Quantity") or "").strip()
        price_raw = (row.get("Price") or "").strip()
        activity_raw = (row.get("Activity Date") or "").strip()

        try:
            quantity = _parse_money(quantity_raw)
        except InvalidOperation:
            issues.append(
                ImportIssue(
                    row_index=row_index,
                    severity="error",
                    code="invalid_number",
                    message=f"第 {row_index} 列：股數格式錯誤",
                )
            )
            return

        if quantity == 0:
            issues.append(
                ImportIssue(
                    row_index=row_index,
                    severity="warn",
                    code="zero_quantity",
                    message=f"第 {row_index} 列：股數為 0，已略過",
                )
            )
            return

        # Some brokers emit sells as negative quantities. Take absolute
        # value; the side already encodes direction.
        if quantity < 0:
            quantity = -quantity

        try:
            price = _parse_money(price_raw)
        except InvalidOperation:
            issues.append(
                ImportIssue(
                    row_index=row_index,
                    severity="error",
                    code="invalid_number",
                    message=f"第 {row_index} 列：價格格式錯誤",
                )
            )
            return

        if price <= 0:
            issues.append(
                ImportIssue(
                    row_index=row_index,
                    severity="error",
                    code="invalid_number",
                    message=f"第 {row_index} 列：價格必須大於 0",
                )
            )
            return

        try:
            executed_at = _parse_date(activity_raw)
        except ValueError:
            issues.append(
                ImportIssue(
                    row_index=row_index,
                    severity="error",
                    code="invalid_date",
                    message=f"第 {row_index} 列：日期格式錯誤",
                )
            )
            return

        external_id = _external_id(
            broker_key=self._source_key,
            activity_date=activity_raw,
            symbol=symbol,
            trans_code=trans_code,
            quantity_raw=quantity_raw,
            price_raw=price_raw,
        )

        records.append(
            TradeImportRecord(
                symbol=symbol,
                side=side,
                shares=quantity,
                price=price,
                executed_at=executed_at,
                external_id=external_id,
                source=self._source_key,
                note=None,
            )
        )


__all__: tuple[str, ...] = ("BrokerCsvImporter",)
