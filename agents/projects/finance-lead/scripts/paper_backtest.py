#!/usr/bin/env python3
"""Backtest paper — SMA crossover + validação cruzada walk-forward temporal."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CSV = ROOT / "fixtures" / "PETR4_sample.csv"
SLIPPAGE_PCT = 0.1


def load_closes(csv_path: Path) -> list[float]:
    closes: list[float] = []
    with csv_path.open(encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            closes.append(float(row["close"]))
    return closes


def sma(values: list[float], window: int) -> list[float | None]:
    out: list[float | None] = []
    for i in range(len(values)):
        if i + 1 < window:
            out.append(None)
        else:
            chunk = values[i + 1 - window : i + 1]
            out.append(sum(chunk) / window)
    return out


def run_backtest_from_closes(
    closes: list[float],
    *,
    fast: int = 5,
    slow: int = 10,
    ticker: str = "PETR4",
    data_source: str = "inline",
) -> dict:
    fast_sma = sma(closes, fast)
    slow_sma = sma(closes, slow)

    position = 0
    entry = 0.0
    trades = 0
    equity = 1.0

    for i in range(1, len(closes)):
        if fast_sma[i] is None or slow_sma[i] is None:
            continue
        prev_f, prev_s = fast_sma[i - 1], slow_sma[i - 1]
        cur_f, cur_s = fast_sma[i], slow_sma[i]
        if prev_f is None or prev_s is None:
            continue

        price = closes[i] * (1 + SLIPPAGE_PCT / 100)

        if position == 0 and prev_f <= prev_s and cur_f > cur_s:
            position = 1
            entry = price
            trades += 1
        elif position == 1 and prev_f >= prev_s and cur_f < cur_s:
            ret = (price - entry) / entry
            equity *= 1 + ret
            position = 0
            trades += 1

    if position == 1 and entry:
        ret = (closes[-1] - entry) / entry
        equity *= 1 + ret

    total_return_pct = round((equity - 1) * 100, 4)
    return {
        "ticker": ticker,
        "data_source": data_source,
        "strategy": f"sma_{fast}_{slow}",
        "slippage_pct": SLIPPAGE_PCT,
        "trade_count": trades,
        "total_return_pct": total_return_pct,
        "bars": len(closes),
    }


def run_backtest(csv_path: Path, fast: int = 5, slow: int = 10) -> dict:
    closes = load_closes(csv_path)
    return run_backtest_from_closes(
        closes,
        fast=fast,
        slow=slow,
        ticker="PETR4",
        data_source=str(csv_path.name),
    )


def walk_forward_cross_validate(
    csv_path: Path,
    *,
    folds: int = 3,
    fast: int = 5,
    slow: int = 10,
) -> dict:
    """Validação cruzada temporal (walk-forward) — folds sequenciais sem lookahead."""
    closes = load_closes(csv_path)
    min_bars = slow + fast + 2
    if len(closes) < min_bars * folds:
        folds = max(2, len(closes) // min_bars)
    if folds < 2:
        return {
            "success": False,
            "error": f"barras insuficientes: {len(closes)}",
        }

    fold_size = len(closes) // folds
    fold_results: list[dict] = []
    for f in range(folds):
        start = f * fold_size
        end = len(closes) if f == folds - 1 else (f + 1) * fold_size
        segment = closes[start:end]
        if len(segment) < min_bars:
            continue
        res = run_backtest_from_closes(
            segment,
            fast=fast,
            slow=slow,
            ticker="PETR4",
            data_source=f"fold_{f + 1}",
        )
        res["fold"] = f + 1
        res["bars_range"] = [start, end]
        fold_results.append(res)

    if len(fold_results) < 2:
        return {"success": False, "error": "menos de 2 folds válidos", "folds": fold_results}

    returns = [float(r["total_return_pct"]) for r in fold_results]
    stdev = round(statistics.pstdev(returns), 4) if len(returns) > 1 else 0.0
    stable = stdev <= 25.0

    return {
        "success": True,
        "method": "walk_forward_temporal",
        "folds_requested": folds,
        "folds_completed": len(fold_results),
        "returns_pct": returns,
        "return_stdev_pct": stdev,
        "stable_across_folds": stable,
        "fold_details": fold_results,
        "pass_threshold_stdev": 25.0,
        "passed": stable and len(fold_results) >= 3,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--cross-validate", action="store_true")
    parser.add_argument("--folds", type=int, default=3)
    args = parser.parse_args()

    if args.cross_validate:
        result = walk_forward_cross_validate(args.csv, folds=args.folds)
    else:
        result = run_backtest(args.csv)

    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(result)


if __name__ == "__main__":
    main()
