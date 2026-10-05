"""Fetch market data — yfinance com fallback para fixture CSV."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT.parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

FIXTURE_DIR = ROOT / "fixtures"
DEFAULT_CSV = FIXTURE_DIR / "PETR4_sample.csv"
OUT_DIR = ROOT / "data" / "market"


def _fixture_path(ticker: str) -> Path:
    specific = FIXTURE_DIR / f"{ticker.upper()}_sample.csv"
    if specific.is_file():
        return specific
    return DEFAULT_CSV


def _load_fixture(ticker: str) -> list[dict[str, str]]:
    path = _fixture_path(ticker)
    if not path.is_file():
        return []
    rows: list[dict[str, str]] = []
    with path.open(encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            rows.append(dict(row))
    return rows


def _yfinance_symbol(ticker: str) -> str:
    """Símbolo Yahoo — tickers B3 precisam do sufixo .SA."""
    t = ticker.upper().strip()
    if t.endswith(".SA"):
        return t
    if re.match(r"^[A-Z]{4}\d{1,2}$", t):
        return f"{t}.SA"
    return t


def _fetch_yfinance(ticker: str, period: str = "1mo") -> list[dict[str, str]]:
    try:
        import yfinance as yf
    except ImportError:
        return []

    symbol = _yfinance_symbol(ticker)
    hist = yf.Ticker(symbol).history(period=period)
    if hist.empty:
        return []
    out: list[dict[str, str]] = []
    for idx, row in hist.iterrows():
        out.append(
            {
                "date": idx.strftime("%Y-%m-%d"),
                "open": f"{row['Open']:.4f}",
                "high": f"{row['High']:.4f}",
                "low": f"{row['Low']:.4f}",
                "close": f"{row['Close']:.4f}",
                "volume": str(int(row["Volume"])),
            }
        )
    return out


def fetch(ticker: str, *, period: str = "1mo", source: str = "auto") -> dict:
    ticker = ticker.upper().strip()
    rows: list[dict[str, str]] = []
    used = "fixture"

    if source in {"auto", "yfinance"}:
        rows = _fetch_yfinance(ticker, period=period)
        if rows:
            used = "yfinance"

    if not rows and source in {"auto", "fixture"}:
        rows = _load_fixture(ticker)
        used = "fixture"

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"{ticker}_{period}.json"
    if not rows and out_path.is_file() and source == "yfinance":
        try:
            existing = json.loads(out_path.read_text(encoding="utf-8"))
            if existing.get("rows"):
                return {
                    "success": True,
                    "path": str(out_path.relative_to(PROJECT_ROOT)),
                    **existing,
                }
        except json.JSONDecodeError:
            pass

    payload = {"ticker": ticker, "period": period, "source": used, "rows": rows, "count": len(rows)}
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"success": bool(rows), "path": str(out_path.relative_to(PROJECT_ROOT)), **payload}


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch OHLCV — yfinance ou fixture")
    parser.add_argument("ticker", nargs="?", default="PETR4")
    parser.add_argument("--period", default="1mo")
    parser.add_argument("--source", choices=["auto", "yfinance", "fixture"], default="auto")
    args = parser.parse_args()
    result = fetch(args.ticker, period=args.period, source=args.source)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
