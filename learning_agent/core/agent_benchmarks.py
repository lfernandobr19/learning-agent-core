"""Benchmarks cegos — tarefas fora do currículo com rubrica objetiva."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from learning_agent.config import PROJECT_ROOT

BENCHMARKS_ROOT = PROJECT_ROOT / "tests" / "agent_benchmarks"
RESULTS_PATH = PROJECT_ROOT / "data" / "benchmark_results.json"

RISK_KEYWORDS = (
    "risco",
    "drawdown",
    "stop",
    "sizing",
    "volatilidade",
    "volatility",
    "var ",
    "value at risk",
    "exposição",
    "exposicao",
    "position size",
    "tamanho da pos",
)


def _load_blind(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def list_blinds(agent: str) -> list[dict[str, Any]]:
    agent_dir = BENCHMARKS_ROOT / agent
    if not agent_dir.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(agent_dir.glob("blind_*.yaml")):
        data = _load_blind(path)
        data["_file"] = path.name
        out.append(data)
    return out


def _score_finance_blind_01(response: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    """Rubrica objetiva — resposta em agents/exams/ ou payload passado."""
    rubric = cfg.get("rubric") or []
    scores: list[dict[str, Any]] = []
    total_weight = sum(int(r.get("weight") or 0) for r in rubric) or 100
    earned = 0.0

    text = json.dumps(response, ensure_ascii=False).lower()
    tickers = set(re.findall(r"\b[A-Z]{4}[0-9]{1,2}\b", json.dumps(response).upper()))
    allowed = set(cfg.get("allowed_tickers") or [])

    for rule in rubric:
        rid = rule.get("id", "")
        weight = int(rule.get("weight") or 0)
        passed = False
        detail = ""

        if rid == "no_invented_prices":
            prices = re.findall(r"R\$\s*[\d.,]+", json.dumps(response))
            invented = "preco_inventado" in text or (len(prices) > 0 and not response.get("data_source"))
            passed = not invented and bool(response.get("data_source"))
            detail = "data_source declarada, sem preços inventados"
        elif rid == "valid_tickers_only":
            bad = tickers - allowed if allowed else set()
            passed = len(bad) == 0 and len(tickers) > 0
            detail = f"tickers={sorted(tickers)}"
        elif rid == "risk_section":
            passed = any(k in text for k in RISK_KEYWORDS)
            detail = "seção de risco presente"
        elif rid == "invalidation":
            passed = any(k in text for k in ("invalid", "invalidação", "invalidacao", "stop"))
            detail = "critério de invalidação"
        elif rid == "no_trade_without_data":
            passed = response.get("recommendation") in ("hold", "watch") or response.get("action") == "hold"
            detail = f"action={response.get('action') or response.get('recommendation')}"
        else:
            passed = bool(rule.get("auto_pass"))
            detail = rule.get("description", "")

        if passed:
            earned += weight
        scores.append({"id": rid, "weight": weight, "passed": passed, "detail": detail})

    composite = round(100 * earned / max(total_weight, 1), 1)
    return {
        "scores": scores,
        "composite": composite,
        "passed": composite >= float(cfg.get("pass_threshold") or 80),
    }


SCORERS = {
    "finance_blind_01": _score_finance_blind_01,
}


def run_blind(agent: str, blind_id: str, response: dict[str, Any] | None = None) -> dict[str, Any]:
    path = BENCHMARKS_ROOT / agent / f"{blind_id}.yaml"
    if not path.is_file():
        return {"success": False, "error": f"Blind não encontrado: {path}"}

    cfg = _load_blind(path)
    scorer_key = cfg.get("scorer", "")
    scorer = SCORERS.get(scorer_key)
    if not scorer:
        return {"success": False, "error": f"Scorer desconhecido: {scorer_key}"}

    if response is None:
        exam_path = PROJECT_ROOT / "agents" / "exams" / f"{agent}_{blind_id}.json"
        if exam_path.is_file():
            payload = json.loads(exam_path.read_text(encoding="utf-8"))
            response = payload.get("response", payload)
        else:
            response = {}

    result = scorer(response, cfg)
    return {
        "success": True,
        "agent": agent,
        "blind_id": blind_id,
        "title": cfg.get("title"),
        "pass_threshold": cfg.get("pass_threshold", 80),
        **result,
    }


def load_results_history() -> dict[str, Any]:
    if not RESULTS_PATH.is_file():
        return {"runs": []}
    try:
        return json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"runs": []}


def save_blind_result(run: dict[str, Any]) -> None:
    from datetime import datetime, timezone

    history = load_results_history()
    run["recorded_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    history.setdefault("runs", []).append(run)
    history["runs"] = history["runs"][-100:]
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


def _best_blind_composite(runs: list[dict[str, Any]]) -> float:
    latest_by_blind: dict[str, float] = {}
    for run in runs:
        blind_id = str(run.get("blind_id") or "")
        if blind_id:
            latest_by_blind[blind_id] = float(run.get("composite") or 0)
    if not latest_by_blind:
        return 0.0
    return round(sum(latest_by_blind.values()) / len(latest_by_blind), 1)


def benchmark_summary(agent: str | None = None) -> dict[str, Any]:
    history = load_results_history()
    runs = history.get("runs") or []
    if agent:
        runs = [r for r in runs if r.get("agent") == agent]

    if not runs:
        # Run static blinds without saved response for display
        agent_name = agent or "finance-lead"
        blinds = list_blinds(agent_name)
        latest = []
        for b in blinds:
            blind_id = b.get("id", b.get("_file", "").replace(".yaml", ""))
            r = run_blind(agent_name, blind_id)
            if r.get("success"):
                latest.append(r)
        avg = round(sum(r.get("composite", 0) for r in latest) / max(len(latest), 1), 1)
        return {
            "agent": agent_name,
            "runs_count": 0,
            "latest_composite": avg,
            "best_score_pct": avg,
            "latest": latest,
            "history": [],
        }

    recent = runs[-4:]
    avg = round(sum(r.get("composite", 0) for r in recent) / max(len(recent), 1), 1)
    best = _best_blind_composite(runs)
    return {
        "agent": agent,
        "runs_count": len(runs),
        "latest_composite": avg,
        "best_score_pct": best,
        "latest": recent[-1:] if recent else [],
        "history": recent,
    }
