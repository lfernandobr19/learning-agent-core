"""Extensões de treino finance-lead — microeconomia, dados diversificados."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

from learning_agent.config import PROJECT_ROOT
from learning_agent.core import indexing, knowledge

FINANCE_ROOT = PROJECT_ROOT / "agents" / "projects" / "finance-lead"
MICRO_PATH = FINANCE_ROOT / "content" / "microeconomics_pf.md"
UNIVERSE_CFG = FINANCE_ROOT / "config" / "diversified_universe.yaml"
DIVERSIFIED_SCRIPT = FINANCE_ROOT / "scripts" / "fetch_diversified_data.py"
DIVERSIFIED_MANIFEST = FINANCE_ROOT / "data" / "diversified_manifest.json"


def ensure_microeconomics_indexed(*, sync_cloud: bool = False) -> dict[str, Any]:
    """Indexa conteúdo de microeconomia PF no knowledge base."""
    if not MICRO_PATH.is_file():
        return {"success": False, "error": "microeconomics_pf.md ausente"}

    text = MICRO_PATH.read_text(encoding="utf-8")
    tags = ["finance-lead", "microeconomics", "microeconomia", "pf", "l6", "fundamentos"]
    indexing.index_file(MICRO_PATH, tags)
    note = knowledge.add_note(
        "Microeconomia PF — oferta, demanda, elasticidade e custo de oportunidade",
        text[:3500],
        tags,
        sync_cloud=sync_cloud,
    )
    return {
        "success": True,
        "action": "microeconomics_indexed",
        "note_id": note.get("id"),
        "path": str(MICRO_PATH.relative_to(PROJECT_ROOT)),
        "chars": len(text),
    }


def run_diversified_data_fetch(*, source: str = "auto") -> dict[str, Any]:
    """Executa fetch multi-ticker e atualiza manifest."""
    if not DIVERSIFIED_SCRIPT.is_file():
        return {"success": False, "error": "fetch_diversified_data.py ausente"}
    proc = subprocess.run(
        [sys.executable, str(DIVERSIFIED_SCRIPT), "--source", source, "--json"],
        capture_output=True,
        text=True,
        timeout=180,
        cwd=str(PROJECT_ROOT),
    )
    if proc.returncode != 0:
        return {"success": False, "error": (proc.stderr or proc.stdout)[-400:]}
    try:
        payload = json.loads(proc.stdout.strip())
    except json.JSONDecodeError:
        return {"success": False, "error": "saída JSON inválida do fetch diversificado"}
    return {"success": bool(payload.get("success")), **payload}


def run_cross_validation_check() -> dict[str, Any]:
    """Executa walk-forward cross-validation (probe F6 / L6)."""
    script = FINANCE_ROOT / "scripts" / "paper_backtest.py"
    if not script.is_file():
        return {"success": False, "error": "paper_backtest.py ausente"}
    proc = subprocess.run(
        [sys.executable, str(script), "--cross-validate", "--json"],
        capture_output=True,
        text=True,
        timeout=90,
        cwd=str(PROJECT_ROOT),
    )
    try:
        payload = json.loads(proc.stdout.strip())
    except json.JSONDecodeError:
        return {"success": False, "error": (proc.stderr or proc.stdout)[-300:]}
    return {
        "success": bool(payload.get("success")),
        "passed": bool(payload.get("passed")),
        "action": "cross_validation_l6",
        **payload,
    }


def diversified_manifest_ok() -> bool:
    if not DIVERSIFIED_MANIFEST.is_file():
        return False
    try:
        data = json.loads(DIVERSIFIED_MANIFEST.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    cfg = yaml.safe_load(UNIVERSE_CFG.read_text(encoding="utf-8")) if UNIVERSE_CFG.is_file() else {}
    min_tickers = int(cfg.get("min_tickers") or 4)
    min_classes = int(cfg.get("min_asset_classes") or 3)
    tickers = data.get("tickers") or []
    classes = {t.get("asset_class") for t in tickers if t.get("success")}
    return len([t for t in tickers if t.get("success")]) >= min_tickers and len(classes) >= min_classes


def microeconomics_indexed() -> bool:
    if not MICRO_PATH.is_file():
        return False
    hits = knowledge.search("microeconomia elasticidade custo oportunidade finance-lead", limit=5)
    if hits:
        return True
    text = MICRO_PATH.read_text(encoding="utf-8").lower()
    return "oferta" in text and "elasticidade" in text
