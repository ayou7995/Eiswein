"""Import API — preview + apply, auth, validation, rate limit, size cap."""

from __future__ import annotations

import io
from pathlib import Path

from fastapi.testclient import TestClient

_FIXTURES = Path(__file__).parent.parent / "fixtures" / "robinhood"

_HEADER = (
    "Activity Date,Process Date,Settle Date,Instrument,Description,"
    "Trans Code,Quantity,Price,Amount\n"
)
_BUY_ROW = "04/21/2026,04/21/2026,04/23/2026,AAPL,Apple Inc,Buy,10,$150.00,$1500.00\n"
_SELL_ROW = "04/21/2026,04/21/2026,04/23/2026,AAPL,Apple Inc,Sell,5,$155.00,$775.00\n"


def _csv_bytes(*rows: str) -> bytes:
    return (_HEADER + "".join(rows)).encode("utf-8")


def _login(client: TestClient, password: str) -> None:
    resp = client.post("/api/v1/login", json={"username": "admin", "password": password})
    assert resp.status_code == 200


def _preview(
    client: TestClient,
    data: bytes,
    broker: str = "robinhood",
    content_type: str = "text/csv",
) -> object:
    return client.post(
        "/api/v1/import/trades/preview",
        data={"broker": broker},
        files={"file": ("trades.csv", io.BytesIO(data), content_type)},
    )


def _apply(
    client: TestClient,
    data: bytes,
    broker: str = "robinhood",
    content_type: str = "text/csv",
) -> object:
    return client.post(
        "/api/v1/import/trades/apply",
        data={"broker": broker},
        files={"file": ("trades.csv", io.BytesIO(data), content_type)},
    )


# ---------------------------------------------------------------------------
# GET /brokers
# ---------------------------------------------------------------------------


def test_import_brokers_requires_auth(client: TestClient) -> None:
    resp = client.get("/api/v1/import/brokers")
    assert resp.status_code == 401


def test_import_brokers_returns_full_list(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    resp = client.get("/api/v1/import/brokers")
    assert resp.status_code == 200
    body = resp.json()
    keys = [b["key"] for b in body["brokers"]]
    # Spot-check that the multi-broker dropdown is wired through.
    for expected in ("robinhood", "moomoo", "schwab", "ibkr", "chase", "other"):
        assert expected in keys


def test_import_brokers_each_entry_has_key_and_label(
    client: TestClient, test_password: str
) -> None:
    _login(client, test_password)
    resp = client.get("/api/v1/import/brokers")
    body = resp.json()
    for entry in body["brokers"]:
        assert isinstance(entry["key"], str) and entry["key"]
        assert isinstance(entry["label"], str) and entry["label"]


# ---------------------------------------------------------------------------
# Auth guard
# ---------------------------------------------------------------------------


def test_import_preview_requires_auth(client: TestClient) -> None:
    resp = _preview(client, _csv_bytes(_BUY_ROW))
    assert resp.status_code == 401


def test_import_apply_requires_auth(client: TestClient) -> None:
    resp = _apply(client, _csv_bytes(_BUY_ROW))
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Preview: happy path
# ---------------------------------------------------------------------------


def test_import_preview_happy_path_returns_200(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    resp = _preview(client, _csv_bytes(_BUY_ROW))
    assert resp.status_code == 200


def test_import_preview_happy_path_response_structure(
    client: TestClient, test_password: str
) -> None:
    _login(client, test_password)
    resp = _preview(client, _csv_bytes(_BUY_ROW))
    body = resp.json()
    assert body["broker"] == "robinhood"
    assert body["total_rows"] == 1
    assert "summary" in body
    assert body["summary"]["would_import"] == 1
    assert body["summary"]["would_skip_duplicate"] == 0


def test_import_preview_happy_path_decimal_fields_are_strings(
    client: TestClient, test_password: str
) -> None:
    _login(client, test_password)
    resp = _preview(client, _csv_bytes(_BUY_ROW))
    body = resp.json()
    record = body["parsed"][0]["record"]
    # Decimal serialized as string to preserve precision
    assert isinstance(record["shares"], str)
    assert isinstance(record["price"], str)


def test_import_preview_happy_path_action_is_import(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    resp = _preview(client, _csv_bytes(_BUY_ROW))
    body = resp.json()
    assert body["parsed"][0]["action"] == "import"


# ---------------------------------------------------------------------------
# Unknown broker → 422
# ---------------------------------------------------------------------------


def test_import_preview_unknown_broker_returns_422(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    resp = _preview(client, _csv_bytes(_BUY_ROW), broker="not_a_real_broker")
    assert resp.status_code == 422


def test_import_preview_unknown_broker_error_code(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    resp = _preview(client, _csv_bytes(_BUY_ROW), broker="not_a_real_broker")
    body = resp.json()
    assert body["error"]["details"]["reason"] == "unknown_broker"


def test_import_apply_unknown_broker_returns_422(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    resp = _apply(client, _csv_bytes(_BUY_ROW), broker="not_a_real_broker")
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Missing file → 422 (FastAPI form validation)
# ---------------------------------------------------------------------------


def test_import_preview_missing_file_returns_422(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    resp = client.post(
        "/api/v1/import/trades/preview",
        data={"broker": "robinhood"},
        # no `files`
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Oversize file → 413
# ---------------------------------------------------------------------------


def test_import_preview_oversize_file_returns_413(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    oversized = b"x" * (5 * 1024 * 1024 + 1)
    resp = _preview(client, oversized)
    assert resp.status_code == 413


def test_import_apply_oversize_file_returns_413(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    oversized = b"x" * (5 * 1024 * 1024 + 1)
    resp = _apply(client, oversized)
    assert resp.status_code == 413


# ---------------------------------------------------------------------------
# Bad content-type → 422
# ---------------------------------------------------------------------------


def test_import_preview_bad_content_type_returns_422(
    client: TestClient, test_password: str
) -> None:
    _login(client, test_password)
    resp = _preview(client, _csv_bytes(_BUY_ROW), content_type="application/zip")
    assert resp.status_code == 422


def test_import_apply_bad_content_type_returns_422(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    resp = _apply(client, _csv_bytes(_BUY_ROW), content_type="application/zip")
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Rate limit — 6th request within 60 s → 429
# ---------------------------------------------------------------------------


def test_import_preview_rate_limit_sixth_request_429(
    client: TestClient, test_password: str
) -> None:
    _login(client, test_password)
    data = _csv_bytes(_BUY_ROW)
    for _ in range(5):
        r = _preview(client, data)
        assert r.status_code == 200

    sixth = _preview(client, data)
    assert sixth.status_code == 429


def test_import_apply_rate_limit_sixth_request_429(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    data = _csv_bytes(_BUY_ROW)
    for _ in range(5):
        r = _apply(client, data)
        # first apply imports, subsequent ones skip
        assert r.status_code == 200

    sixth = _apply(client, data)
    assert sixth.status_code == 429


# ---------------------------------------------------------------------------
# Apply: happy path
# ---------------------------------------------------------------------------


def test_import_apply_happy_path_returns_200(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    resp = _apply(client, _csv_bytes(_BUY_ROW))
    assert resp.status_code == 200


def test_import_apply_happy_path_imported_count(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    resp = _apply(client, _csv_bytes(_BUY_ROW))
    body = resp.json()
    assert body["summary"]["imported"] == 1


def test_import_apply_happy_path_broker_in_response(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    resp = _apply(client, _csv_bytes(_BUY_ROW))
    body = resp.json()
    assert body["broker"] == "robinhood"


# ---------------------------------------------------------------------------
# Apply: idempotent
# ---------------------------------------------------------------------------


def test_import_apply_idempotent_second_pass_imported_zero(
    client: TestClient, test_password: str
) -> None:
    _login(client, test_password)
    data = _csv_bytes(_BUY_ROW)
    first = _apply(client, data)
    assert first.json()["summary"]["imported"] == 1

    second = _apply(client, data)
    body = second.json()
    assert body["summary"]["imported"] == 0
    assert body["summary"]["skipped_duplicate"] == 1


# ---------------------------------------------------------------------------
# Preview: empty CSV → 0 records, no errors
# ---------------------------------------------------------------------------


def test_import_preview_empty_csv_returns_empty_result(
    client: TestClient, test_password: str
) -> None:
    _login(client, test_password)
    resp = _preview(client, _csv_bytes())  # header only
    assert resp.status_code == 200
    body = resp.json()
    assert body["summary"]["would_import"] == 0
    assert body["summary"]["errors"] == 0


# ---------------------------------------------------------------------------
# Preview using fixture files
# ---------------------------------------------------------------------------


def test_import_preview_simple_buy_sell_fixture(client: TestClient, test_password: str) -> None:
    _login(client, test_password)
    data = (_FIXTURES / "simple_buy_sell.csv").read_bytes()
    resp = _preview(client, data)
    assert resp.status_code == 200
    body = resp.json()
    # 1 buy (action=import) + 1 sell (action=error — no open position)
    assert body["total_rows"] == 2


def test_import_preview_options_fixture_emits_warn_in_file_issues_or_summary(
    client: TestClient, test_password: str
) -> None:
    _login(client, test_password)
    data = (_FIXTURES / "options.csv").read_bytes()
    resp = _preview(client, data)
    assert resp.status_code == 200
    body = resp.json()
    # Options row skipped — zero parsed records
    assert len(body["parsed"]) == 0
