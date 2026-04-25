"""BrokerCsvImporter — parsing contract, edge cases, determinism.

Exercised via the ``robinhood`` source key because that is the broker
the historical fixtures were captured against. The same parser serves
every supported broker; broker-specific behaviour (if any is ever
needed) would warrant a dedicated test module.
"""

from __future__ import annotations

import hashlib
import io
from datetime import UTC
from decimal import Decimal
from pathlib import Path

import pytest

from app.ingestion.importers.broker_csv import BrokerCsvImporter

_FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "robinhood"


def _fixture(name: str) -> io.BytesIO:
    return io.BytesIO((_FIXTURES / name).read_bytes())


@pytest.fixture
def importer() -> BrokerCsvImporter:
    return BrokerCsvImporter(source_key="robinhood")


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_simple_buy_sell_returns_two_records(importer: BrokerCsvImporter) -> None:
    records, issues = importer.parse(_fixture("simple_buy_sell.csv"))
    assert len(records) == 2
    assert len(issues) == 0


def test_simple_buy_sell_sides_correct(importer: BrokerCsvImporter) -> None:
    records, _ = importer.parse(_fixture("simple_buy_sell.csv"))
    sides = [r.side for r in records]
    assert sides == ["buy", "sell"]


def test_simple_buy_sell_external_ids_are_32_char_hex(
    importer: BrokerCsvImporter,
) -> None:
    records, _ = importer.parse(_fixture("simple_buy_sell.csv"))
    for record in records:
        assert len(record.external_id) == 32
        assert all(c in "0123456789abcdef" for c in record.external_id)


def test_simple_buy_sell_external_ids_are_deterministic(
    importer: BrokerCsvImporter,
) -> None:
    records_first, _ = importer.parse(_fixture("simple_buy_sell.csv"))
    records_second, _ = importer.parse(_fixture("simple_buy_sell.csv"))
    assert [r.external_id for r in records_first] == [r.external_id for r in records_second]


def test_simple_buy_sell_external_ids_are_sha256_prefix(
    importer: BrokerCsvImporter,
) -> None:
    records, _ = importer.parse(_fixture("simple_buy_sell.csv"))
    buy = records[0]
    key = "robinhood|04/21/2026|AAPL|Buy|10|$150.00"
    expected = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
    assert buy.external_id == expected


def test_simple_buy_sell_source_is_robinhood(importer: BrokerCsvImporter) -> None:
    records, _ = importer.parse(_fixture("simple_buy_sell.csv"))
    assert all(r.source == "robinhood" for r in records)


def test_simple_buy_sell_executed_at_is_utc(importer: BrokerCsvImporter) -> None:
    records, _ = importer.parse(_fixture("simple_buy_sell.csv"))
    for record in records:
        assert record.executed_at.tzinfo is not None
        assert record.executed_at.tzinfo == UTC or str(record.executed_at.tzinfo) in (
            "UTC",
            "tzfile('UTC')",
        )


def test_simple_buy_sell_date_parsed_from_et_to_utc(
    importer: BrokerCsvImporter,
) -> None:
    records, _ = importer.parse(_fixture("simple_buy_sell.csv"))
    buy = records[0]
    assert buy.executed_at.year == 2026
    assert buy.executed_at.month == 4
    assert buy.executed_at.day == 21
    assert buy.executed_at.hour >= 4


# ---------------------------------------------------------------------------
# Junk rows silently skipped
# ---------------------------------------------------------------------------


def test_with_junk_returns_two_records_no_issues(importer: BrokerCsvImporter) -> None:
    records, issues = importer.parse(_fixture("with_junk.csv"))
    assert len(records) == 2
    assert len(issues) == 0


def test_with_junk_only_buy_and_sell_codes_parsed(importer: BrokerCsvImporter) -> None:
    records, _ = importer.parse(_fixture("with_junk.csv"))
    assert {r.side for r in records} == {"buy", "sell"}


# ---------------------------------------------------------------------------
# Options skipped with warning
# ---------------------------------------------------------------------------


def test_options_returns_zero_records(importer: BrokerCsvImporter) -> None:
    records, _ = importer.parse(_fixture("options.csv"))
    assert len(records) == 0


def test_options_emits_warn_options_skipped(importer: BrokerCsvImporter) -> None:
    _, issues = importer.parse(_fixture("options.csv"))
    assert len(issues) == 1
    assert issues[0].severity == "warn"
    assert issues[0].code == "options_skipped"


def test_options_issue_has_positive_row_index(importer: BrokerCsvImporter) -> None:
    _, issues = importer.parse(_fixture("options.csv"))
    assert issues[0].row_index >= 1


# ---------------------------------------------------------------------------
# Zero quantity
# ---------------------------------------------------------------------------


def test_zero_qty_returns_zero_records(importer: BrokerCsvImporter) -> None:
    records, _ = importer.parse(_fixture("zero_qty.csv"))
    assert len(records) == 0


def test_zero_qty_emits_warn_zero_quantity(importer: BrokerCsvImporter) -> None:
    _, issues = importer.parse(_fixture("zero_qty.csv"))
    assert len(issues) == 1
    assert issues[0].severity == "warn"
    assert issues[0].code == "zero_quantity"


# ---------------------------------------------------------------------------
# Bad number (invalid price)
# ---------------------------------------------------------------------------


def test_bad_number_returns_zero_records(importer: BrokerCsvImporter) -> None:
    records, _ = importer.parse(_fixture("bad_number.csv"))
    assert len(records) == 0


def test_bad_number_emits_one_error(importer: BrokerCsvImporter) -> None:
    _, issues = importer.parse(_fixture("bad_number.csv"))
    assert len(issues) == 1
    assert issues[0].severity == "error"


# ---------------------------------------------------------------------------
# Fractional shares — Decimal, not float
# ---------------------------------------------------------------------------


def test_fractional_preserves_exact_decimal(importer: BrokerCsvImporter) -> None:
    records, issues = importer.parse(_fixture("fractional.csv"))
    assert len(records) == 1
    assert len(issues) == 0
    assert records[0].shares == Decimal("0.5431")
    assert records[0].price == Decimal("123.45")


def test_fractional_shares_type_is_decimal(importer: BrokerCsvImporter) -> None:
    records, _ = importer.parse(_fixture("fractional.csv"))
    assert type(records[0].shares) is Decimal
    assert type(records[0].price) is Decimal


# ---------------------------------------------------------------------------
# Empty file (header only)
# ---------------------------------------------------------------------------


def test_empty_returns_no_records_no_issues(importer: BrokerCsvImporter) -> None:
    records, issues = importer.parse(_fixture("empty.csv"))
    assert len(records) == 0
    assert len(issues) == 0


# ---------------------------------------------------------------------------
# Malformed CSV (missing required column)
# ---------------------------------------------------------------------------


def test_malformed_returns_zero_records(importer: BrokerCsvImporter) -> None:
    records, _ = importer.parse(_fixture("malformed.csv"))
    assert len(records) == 0


def test_malformed_emits_file_level_error(importer: BrokerCsvImporter) -> None:
    _, issues = importer.parse(_fixture("malformed.csv"))
    assert len(issues) == 1
    assert issues[0].row_index == -1
    assert issues[0].severity == "error"


def test_malformed_error_code_is_missing_columns(importer: BrokerCsvImporter) -> None:
    _, issues = importer.parse(_fixture("malformed.csv"))
    assert issues[0].code == "missing_columns"


# ---------------------------------------------------------------------------
# Class-share symbol (BRK.B)
# ---------------------------------------------------------------------------


def test_class_shares_parses_brk_b(importer: BrokerCsvImporter) -> None:
    records, issues = importer.parse(_fixture("class_shares.csv"))
    assert len(records) == 1
    assert len(issues) == 0
    assert records[0].symbol == "BRK.B"


# ---------------------------------------------------------------------------
# Money format: $1,234.56 and parenthesised negative
# ---------------------------------------------------------------------------


def test_money_format_comma_price_parses_correctly(
    importer: BrokerCsvImporter,
) -> None:
    records, issues = importer.parse(_fixture("money_formats.csv"))
    assert len(issues) == 0
    assert records[0].price == Decimal("1234.56")


def test_money_format_parenthesised_negative_parses(
    importer: BrokerCsvImporter,
) -> None:
    from app.ingestion.importers.broker_csv import _parse_money

    result = _parse_money("($5.00)")
    assert result == Decimal("-5.00")


def test_money_format_dollar_stripped(importer: BrokerCsvImporter) -> None:
    from app.ingestion.importers.broker_csv import _parse_money

    assert _parse_money("$42.00") == Decimal("42.00")


# ---------------------------------------------------------------------------
# Date parsing: various formats
# ---------------------------------------------------------------------------


def test_date_parsing_mm_dd_yyyy(importer: BrokerCsvImporter) -> None:
    from app.ingestion.importers.broker_csv import _parse_date

    dt = _parse_date("04/21/2026")
    assert dt.tzinfo is not None
    assert dt.year == 2026
    assert dt.month == 4
    assert dt.day == 21


def test_date_parsing_iso_format(importer: BrokerCsvImporter) -> None:
    from app.ingestion.importers.broker_csv import _parse_date

    dt = _parse_date("2026-04-21")
    assert dt.year == 2026
    assert dt.month == 4


def test_date_parsing_short_year(importer: BrokerCsvImporter) -> None:
    from app.ingestion.importers.broker_csv import _parse_date

    dt = _parse_date("04/21/26")
    assert dt.year == 2026


def test_date_parsing_empty_raises(importer: BrokerCsvImporter) -> None:
    from app.ingestion.importers.broker_csv import _parse_date

    with pytest.raises(ValueError):
        _parse_date("")


# ---------------------------------------------------------------------------
# Truly empty file (zero bytes)
# ---------------------------------------------------------------------------


def test_truly_empty_bytes_emits_file_error(importer: BrokerCsvImporter) -> None:
    _, issues = importer.parse(io.BytesIO(b""))
    assert len(issues) == 1
    assert issues[0].row_index == -1
    assert issues[0].severity == "error"
    assert issues[0].code == "empty_file"


# ---------------------------------------------------------------------------
# SOURCE_KEY
# ---------------------------------------------------------------------------


def test_source_key_round_trips_constructor_arg() -> None:
    assert BrokerCsvImporter(source_key="robinhood").SOURCE_KEY == "robinhood"


def test_source_key_distinct_per_broker() -> None:
    assert BrokerCsvImporter(source_key="schwab").SOURCE_KEY == "schwab"
    assert BrokerCsvImporter(source_key="moomoo").SOURCE_KEY == "moomoo"


def test_source_key_changes_external_id_namespace() -> None:
    a = BrokerCsvImporter(source_key="robinhood")
    b = BrokerCsvImporter(source_key="schwab")
    rec_a, _ = a.parse(_fixture("simple_buy_sell.csv"))
    rec_b, _ = b.parse(_fixture("simple_buy_sell.csv"))
    assert rec_a[0].external_id != rec_b[0].external_id


def test_source_key_empty_string_rejected() -> None:
    with pytest.raises(ValueError):
        BrokerCsvImporter(source_key="")
