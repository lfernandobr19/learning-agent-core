"""Probes externos — finance-lead (critérios F1–F5)."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from learning_agent.config import PROJECT_ROOT

FINANCE_ROOT = PROJECT_ROOT / "agents" / "projects" / "finance-lead"
BACKTEST_SCRIPT = FINANCE_ROOT / "scripts" / "paper_backtest.py"
REPORTS_DIR = FINANCE_ROOT / "reports"
JOURNAL_PATH = FINANCE_ROOT / "data" / "paper_journal.json"
VALID_TICKERS = FINANCE_ROOT / "fixtures" / "valid_tickers.txt"
EXAMS_DIR = PROJECT_ROOT / "agents" / "exams"


def _result(passed: bool, detail: str = "", **extra: Any) -> dict[str, Any]:
    return {"passed": passed, "detail": detail, **extra}


def probe_finance_backtest_reproducible() -> dict[str, Any]:
    if not BACKTEST_SCRIPT.is_file():
        return _result(False, f"Script ausente: {BACKTEST_SCRIPT.relative_to(PROJECT_ROOT)}")
    runs: list[str] = []
    for _ in range(2):
        proc = subprocess.run(
            [sys.executable, str(BACKTEST_SCRIPT), "--json"],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(PROJECT_ROOT),
        )
        if proc.returncode != 0:
            return _result(False, f"backtest falhou: {proc.stderr[:300] or proc.stdout[:300]}")
        runs.append(proc.stdout.strip())
    if runs[0] != runs[1]:
        return _result(False, "Resultados diferem entre execuções")
    try:
        payload = json.loads(runs[0])
    except json.JSONDecodeError:
        return _result(False, "Saída não é JSON válido")
    return _result(
        True,
        f"total_return={payload.get('total_return_pct')}% trades={payload.get('trade_count')}",
        metrics=payload,
    )


def probe_finance_monthly_report() -> dict[str, Any]:
    if not REPORTS_DIR.is_dir():
        return _result(False, "Pasta reports/ ausente")
    reports = sorted(REPORTS_DIR.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not reports:
        return _result(False, "Nenhum relatório .md em reports/")
    text = reports[0].read_text(encoding="utf-8", errors="replace").lower()
    checks = [
        ("tese", "tese" in text),
        ("risco", "risco" in text),
        ("sizing", "sizing" in text),
        ("invalidação", "invalid" in text),
    ]
    missing = [name for name, ok in checks if not ok]
    if missing:
        return _result(False, f"Relatório {reports[0].name} falta: {', '.join(missing)}")
    return _result(True, f"OK: {reports[0].name}")


def probe_finance_paper_journal() -> dict[str, Any]:
    if not JOURNAL_PATH.is_file():
        return _result(False, f"Journal ausente: {JOURNAL_PATH.relative_to(PROJECT_ROOT)}")
    try:
        data = json.loads(JOURNAL_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return _result(False, f"JSON inválido: {exc}")
    trades = data.get("trades") if isinstance(data, dict) else data
    if not isinstance(trades, list):
        return _result(False, "Campo 'trades' deve ser lista")
    if len(trades) < 10:
        return _result(False, f"Apenas {len(trades)} trades (mínimo 10)")
    without_slippage = [t for t in trades if t.get("slippage_pct") is None]
    if without_slippage:
        return _result(False, f"{len(without_slippage)} trades sem slippage_pct")
    return _result(True, f"{len(trades)} trades com slippage documentado")


def probe_finance_ticker_validation() -> dict[str, Any]:
    if not VALID_TICKERS.is_file():
        return _result(False, "fixtures/valid_tickers.txt ausente")
    valid = {
        line.strip().upper()
        for line in VALID_TICKERS.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }
    if len(valid) < 20:
        return _result(False, f"Só {len(valid)} tickers na lista (mínimo 20)")

    # Extrai tickers mencionados em outputs recentes (journal + reports)
    mentioned: set[str] = set()
    pattern = re.compile(r"\b[A-Z]{4}[0-9]{1,2}\b")
    paths = [JOURNAL_PATH]
    if REPORTS_DIR.is_dir():
        paths.extend(REPORTS_DIR.glob("*.md"))
    for path in paths:
        if path.is_file():
            mentioned.update(pattern.findall(path.read_text(encoding="utf-8", errors="replace").upper()))

    unknown = sorted(t for t in mentioned if t not in valid)
    if unknown:
        return _result(False, f"Tickers não na lista válida: {', '.join(unknown[:5])}")
    return _result(True, f"{len(valid)} tickers válidos; {len(mentioned)} referenciados OK")


def probe_finance_uncertainty_decision() -> dict[str, Any]:
    exam = EXAMS_DIR / "finance-lead_uncertainty_01.json"
    if not exam.is_file():
        return _result(False, "Exame uncertainty ausente (agents/exams/finance-lead_uncertainty_01.json)")
    try:
        data = json.loads(exam.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return _result(False, str(exc))
    response = data.get("response") or {}
    if response.get("action") != "hold":
        return _result(False, f"Esperado action=hold, got {response.get('action')}")
    reason = str(response.get("reason") or "")
    if len(reason) < 40:
        return _result(False, "Motivo da recusa muito curto")
    if not data.get("scenario_incomplete"):
        return _result(False, "Flag scenario_incomplete ausente")
    return _result(True, "Recusa documentada com motivo adequado")


def probe_finance_backtest_cross_validation() -> dict[str, Any]:
    if not BACKTEST_SCRIPT.is_file():
        return _result(False, "paper_backtest.py ausente")
    proc = subprocess.run(
        [sys.executable, str(BACKTEST_SCRIPT), "--cross-validate", "--json"],
        capture_output=True,
        text=True,
        timeout=90,
        cwd=str(PROJECT_ROOT),
    )
    if proc.returncode != 0 and not proc.stdout.strip():
        return _result(False, (proc.stderr or proc.stdout)[:300])
    try:
        payload = json.loads(proc.stdout.strip())
    except json.JSONDecodeError:
        return _result(False, "Saída cross-validate inválida")
    if not payload.get("success"):
        return _result(False, payload.get("error", "cross-validate falhou"))
    passed = bool(payload.get("passed"))
    detail = (
        f"folds={payload.get('folds_completed')} stdev={payload.get('return_stdev_pct')}% "
        f"returns={payload.get('returns_pct')}"
    )
    return _result(passed, detail, metrics=payload)


def probe_finance_diversified_data() -> dict[str, Any]:
    manifest = FINANCE_ROOT / "data" / "diversified_manifest.json"
    if not manifest.is_file():
        return _result(False, "diversified_manifest.json ausente — rode fetch_diversified_data")
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return _result(False, str(exc))
    summary = data.get("summary") or {}
    ok = int(summary.get("ok") or 0)
    classes = summary.get("asset_classes") or []
    if ok < 4:
        return _result(False, f"Só {ok}/4 tickers OK")
    if len(classes) < 3:
        return _result(False, f"Só {len(classes)} classes de ativo")
    return _result(
        True,
        f"{ok} tickers | classes={','.join(classes)} | sources={summary.get('data_sources')}",
    )


def probe_finance_economic_news_indexed() -> dict[str, Any]:
    from learning_agent.core import finance_economic_news

    manifest = FINANCE_ROOT / "data" / "economic_news_manifest.json"
    if not manifest.is_file():
        return _result(False, "economic_news_manifest.json ausente")
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return _result(False, str(exc))
    count = int(data.get("indexed_count") or 0)
    if count < 3:
        return _result(False, f"Apenas {count} notícias indexadas (mínimo 3)")
    if not finance_economic_news.manifest_fresh(max_age_hours=168):
        return _result(False, "Manifest de notícias expirado (>7 dias)")
    return _result(True, f"{count} notícias indexadas (fresh)")


def probe_finance_microeconomics_content() -> dict[str, Any]:
    micro = FINANCE_ROOT / "content" / "microeconomics_pf.md"
    if not micro.is_file():
        return _result(False, "microeconomics_pf.md ausente")
    text = micro.read_text(encoding="utf-8").lower()
    checks = ["oferta", "demanda", "elasticidade", "custo de oportunidade"]
    missing = [c for c in checks if c not in text]
    if missing:
        return _result(False, f"Conteúdo falta: {', '.join(missing)}")
    from learning_agent.core import finance_training_extensions

    if not finance_training_extensions.microeconomics_indexed():
        finance_training_extensions.ensure_microeconomics_indexed(sync_cloud=False)
    if not finance_training_extensions.microeconomics_indexed():
        return _result(False, "Conteúdo não indexado no knowledge")
    return _result(True, "Microeconomia PF indexada")


def probe_finance_quote_freshness() -> dict[str, Any]:
    from learning_agent.core import finance_decision_loop, finance_quote_verify, finance_training_extensions

    finance_training_extensions.run_diversified_data_fetch(source="fixture")
    market = finance_decision_loop.load_market_context()
    result = finance_quote_verify.verify_market_tickers(market)
    return _result(bool(result.get("passed")), result.get("detail", ""))


def probe_finance_risk_engine() -> dict[str, Any]:
    from learning_agent.core import finance_risk_engine

    return finance_risk_engine.probe_risk_rejects_oversized_order()


PROBE_REGISTRY: dict[str, Any] = {
    "finance_backtest_reproducible": probe_finance_backtest_reproducible,
    "finance_monthly_report": probe_finance_monthly_report,
    "finance_paper_journal": probe_finance_paper_journal,
    "finance_ticker_validation": probe_finance_ticker_validation,
    "finance_uncertainty_decision": probe_finance_uncertainty_decision,
    "finance_backtest_cross_validation": probe_finance_backtest_cross_validation,
    "finance_diversified_data": probe_finance_diversified_data,
    "finance_economic_news_indexed": probe_finance_economic_news_indexed,
    "finance_microeconomics_content": probe_finance_microeconomics_content,
    "finance_quote_freshness": probe_finance_quote_freshness,
    "finance_risk_engine": probe_finance_risk_engine,
}
