"""Fixture generator — pulls real OHLCV via yfinance offline (H4).

Run MANUALLY when you want to refresh the fixture snapshots in
``backend/tests/fixtures/``. The indicator tests themselves do NOT
call this — they load the parquet files on disk so CI stays hermetic.

Why parquet: tests need a reproducible input; committing the raw bytes
guarantees that formula-change regressions are attributable to the
formula, not to upstream data drift.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import yfinance as yf

DEFAULT_SYMBOLS = ("SPY", "AAPL", "^VIX")
DEFAULT_PERIOD = "2y"
FIXTURES_DIR = Path(__file__).parent.parent / "backend" / "tests" / "fixtures"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate indicator test fixtures from yfinance.",
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=list(DEFAULT_SYMBOLS),
        help="Tickers to fetch (default: SPY AAPL ^VIX).",
    )
    parser.add_argument(
        "--period",
        default=DEFAULT_PERIOD,
        help="yfinance period string (default: 2y).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=FIXTURES_DIR,
        help=f"Directory to write parquet files (default: {FIXTURES_DIR}).",
    )
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)

    today = date.today()
    for symbol in args.symbols:
        frame = yf.download(
            symbol,
            period=args.period,
            auto_adjust=True,
            threads=False,
            progress=False,
        )
        if frame is None or frame.empty:
            print(f"[warn] empty frame for {symbol}; skipping", file=sys.stderr)
            continue
        frame.columns = [str(c).lower() for c in frame.columns]
        safe = symbol.replace("^", "")
        out = args.output_dir / f"{safe}_{today.isoformat()}.parquet"
        frame.to_parquet(out)
        print(f"[ok] wrote {out} ({len(frame)} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
