#!/usr/bin/env python3
"""Fetch diversificado — multi-ticker, multi-classe para treino finance-lead."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT.parents[2]
CFG = ROOT / "config" / "diversified_universe.yaml"
MANIFEST = ROOT / "data" / "diversified_manifest.json"


def _load_fetch():
    spec = importlib.util.spec_from_file_location(
        "fetch_market_data",
        ROOT / "scripts" / "fetch_market_data.py",
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(mod)
    return mod.fetch


def run(*, source: str = "auto", period: str = "1mo") -> dict[str, Any]:
    cfg = yaml.safe_load(CFG.read_text(encoding="utf-8")) if CFG.is_file() else {}
    tickers_cfg = cfg.get("tickers") or []
    fetch_fn = _load_fetch()
    results: list[dict[str, Any]] = []
    sources_used: set[str] = set()

    for item in tickers_cfg:
        symbol = str(item.get("symbol", "")).upper()
        if not symbol:
            continue
        row = fetch_fn(symbol, period=period, source=source)
        row["asset_class"] = item.get("asset_class")
        row["sector"] = item.get("sector")
        row["success"] = bool(row.get("success"))
        results.append(row)
        if row.get("source"):
            sources_used.add(str(row["source"]))

    asset_classes = {r.get("asset_class") for r in results if r.get("success")}
    ok_count = sum(1 for r in results if r.get("success"))
    min_tickers = int(cfg.get("min_tickers") or 4)
    min_classes = int(cfg.get("min_asset_classes") or 3)

    payload = {
        "success": ok_count >= min_tickers and len(asset_classes) >= min_classes,
        "tickers": results,
        "summary": {
            "ok": ok_count,
            "total": len(results),
            "asset_classes": sorted(c for c in asset_classes if c),
            "data_sources": sorted(sources_used),
            "diversification_score": round(100 * len(asset_classes) / max(min_classes, 1), 1),
        },
    }
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    payload["manifest"] = str(MANIFEST.relative_to(PROJECT_ROOT))
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch diversificado finance-lead")
    parser.add_argument("--source", choices=["auto", "yfinance", "fixture"], default="auto")
    parser.add_argument("--period", default="1mo")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = run(source=args.source, period=args.period)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
