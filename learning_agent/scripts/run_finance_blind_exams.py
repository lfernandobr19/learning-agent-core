"""Gera respostas frescas do finance-lead para blinds e pontua com rubrica."""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from learning_agent.config import PROJECT_ROOT
from learning_agent.core import agent_benchmarks, llm
from learning_agent.core.finance_blind_exam import BLIND_EXAM_SYSTEM

AGENT = "finance-lead"
EXAMS = PROJECT_ROOT / "agents" / "exams"
BENCH = PROJECT_ROOT / "tests" / "agent_benchmarks" / AGENT
LOG = PROJECT_ROOT / "data" / "blind_exams_last.json"
BATCH_LOG = PROJECT_ROOT / "data" / "blind_exams_batch_last.json"

SYSTEM = BLIND_EXAM_SYSTEM


def _backup_blind_artifact(path: Path) -> str | None:
    if not path.is_file():
        return None
    dest_dir = PROJECT_ROOT / "data" / "backups" / "blind"
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    dest = dest_dir / f"{path.stem}-{stamp}{path.suffix}"
    shutil.copy2(path, dest)
    return str(dest.relative_to(PROJECT_ROOT))


def _parse_json(raw: str) -> dict[str, Any]:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[\w]*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```$", "", cleaned)
    data = json.loads(cleaned)
    if not isinstance(data, dict):
        raise ValueError("resposta nao e objeto JSON")
    return data


def _load_blind_cfg(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _generate_response(cfg: dict[str, Any]) -> tuple[dict[str, Any], str]:
    blind_id = str(cfg.get("id") or "")
    title = cfg.get("title") or blind_id
    scenario = cfg.get("scenario") or title
    allowed = cfg.get("allowed_tickers") or []
    prompt = (
        f"Cenario blind exam: {scenario}\n"
        f"Titulo: {title}\n"
        f"Tickers permitidos: {allowed}\n"
        "Responda JSON com action hold ou watch."
    )
    raw, model = llm.chat_with_fallback(
        [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": prompt},
        ],
        max_tokens=600,
        temperature=0.2,
    )
    return _parse_json(raw), model


def _stdev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    var = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return round(math.sqrt(var), 2)


def _summarize_blind_runs(blind_id: str, runs: list[dict[str, Any]], *, threshold: float) -> dict[str, Any]:
    ok = [r for r in runs if r.get("success")]
    scores = [float(r.get("composite") or 0) for r in ok]
    passed = [r for r in ok if r.get("passed")]
    below = [r for r in ok if float(r.get("composite") or 0) < threshold]

    criteria_failures: dict[str, int] = {}
    for run in ok:
        for score in run.get("scores") or []:
            if not score.get("passed"):
                rid = str(score.get("id") or "?")
                criteria_failures[rid] = criteria_failures.get(rid, 0) + 1

    return {
        "blind_id": blind_id,
        "title": ok[0].get("title") if ok else blind_id,
        "attempts": len(runs),
        "successful": len(ok),
        "parse_errors": len(runs) - len(ok),
        "pass_threshold": threshold,
        "mean_composite": round(sum(scores) / max(len(scores), 1), 1) if scores else 0.0,
        "stdev_composite": _stdev(scores),
        "min_composite": round(min(scores), 1) if scores else 0.0,
        "max_composite": round(max(scores), 1) if scores else 0.0,
        "pass_count": len(passed),
        "fail_count": len(ok) - len(passed),
        "below_threshold_count": len(below),
        "pass_rate_pct": round(100 * len(passed) / max(len(ok), 1), 1),
        "scores": scores,
        "criteria_failures": criteria_failures,
        "runs": runs,
    }


def run_single_blind(
    cfg: dict[str, Any],
    *,
    use_llm: bool = True,
    persist_exam: bool = True,
    persist_benchmark: bool = True,
) -> dict[str, Any]:
    blind_id = str(cfg.get("id") or "")
    scenario = cfg.get("scenario") or cfg.get("title") or blind_id
    exam_path = EXAMS / f"{AGENT}_{blind_id}.json"

    response: dict[str, Any] | None = None
    model = "cached"
    if use_llm:
        if not llm.is_chat_configured():
            return {"success": False, "blind_id": blind_id, "error": "LLM nao configurado (Ollama/Groq)"}
        try:
            response, model = _generate_response(cfg)
        except Exception as exc:
            return {"success": False, "blind_id": blind_id, "error": str(exc)}

    if persist_exam and response is not None:
        payload = {
            "agent": AGENT,
            "blind_id": blind_id,
            "scenario": scenario,
            "response": response,
            "model": model,
        }
        exam_path.parent.mkdir(parents=True, exist_ok=True)
        exam_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    scored = agent_benchmarks.run_blind(AGENT, blind_id, response=response)
    if scored.get("success") and persist_benchmark:
        agent_benchmarks.save_blind_result(scored)
    return {**scored, "model": model}


def run_exams(*, blind_ids: list[str] | None = None, use_llm: bool = True) -> dict[str, Any]:
    paths = sorted(BENCH.glob("blind_*.yaml"))
    if blind_ids:
        wanted = set(blind_ids)
        paths = [p for p in paths if _load_blind_cfg(p).get("id") in wanted]

    runs = [run_single_blind(_load_blind_cfg(path), use_llm=use_llm) for path in paths]
    ok = [r for r in runs if r.get("success")]
    avg = round(sum(r.get("composite", 0) for r in ok) / max(len(ok), 1), 1)
    passed_all = all(r.get("passed") for r in ok) if ok else False
    report = {
        "success": bool(ok) and passed_all,
        "agent": AGENT,
        "pass_threshold": ok[0].get("pass_threshold") if ok else 80,
        "average_composite": avg,
        "runs": runs,
    }
    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def run_batch(*, repeats: int = 5, blind_ids: list[str] | None = None) -> dict[str, Any]:
    if not llm.is_chat_configured():
        return {"success": False, "error": "LLM nao configurado (Ollama/Groq)"}

    paths = sorted(BENCH.glob("blind_*.yaml"))
    if blind_ids:
        wanted = set(blind_ids)
        paths = [p for p in paths if _load_blind_cfg(p).get("id") in wanted]

    threshold = float(_load_blind_cfg(paths[0]).get("pass_threshold") or 80) if paths else 80.0
    by_blind: dict[str, list[dict[str, Any]]] = {}

    for path in paths:
        cfg = _load_blind_cfg(path)
        blind_id = str(cfg.get("id") or path.stem)
        by_blind[blind_id] = []
        for attempt in range(1, repeats + 1):
            result = run_single_blind(
                cfg,
                use_llm=True,
                persist_exam=(attempt == repeats),
                persist_benchmark=True,
            )
            result["attempt"] = attempt
            by_blind[blind_id].append(result)

    summaries = [_summarize_blind_runs(bid, runs, threshold=threshold) for bid, runs in by_blind.items()]
    all_scores = [s for sm in summaries for s in sm.get("scores") or []]
    overall = {
        "mean_composite": round(sum(all_scores) / max(len(all_scores), 1), 1) if all_scores else 0.0,
        "stdev_composite": _stdev(all_scores),
        "total_runs": sum(sm.get("successful", 0) for sm in summaries),
        "total_pass": sum(sm.get("pass_count", 0) for sm in summaries),
        "total_fail": sum(sm.get("fail_count", 0) for sm in summaries),
        "total_below_threshold": sum(sm.get("below_threshold_count", 0) for sm in summaries),
    }

    report = {
        "success": overall["total_fail"] == 0 and overall["total_runs"] > 0,
        "agent": AGENT,
        "repeats": repeats,
        "pass_threshold": threshold,
        "recorded_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "overall": overall,
        "blinds": summaries,
    }
    BATCH_LOG.parent.mkdir(parents=True, exist_ok=True)
    BATCH_LOG.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["backup_path"] = _backup_blind_artifact(BATCH_LOG)
    return report


def run_fresh_blinds(*, blind_ids: list[str] | None = None) -> dict[str, Any]:
    """Opção C — 1 resposta LLM fresca por blind (sem repetir 5×)."""
    if not llm.is_chat_configured():
        return {"success": False, "error": "LLM nao configurado (Ollama/Groq)"}

    paths = sorted(BENCH.glob("blind_*.yaml"))
    if blind_ids:
        wanted = set(blind_ids)
        paths = [p for p in paths if _load_blind_cfg(p).get("id") in wanted]

    runs: list[dict[str, Any]] = []
    for path in paths:
        cfg = _load_blind_cfg(path)
        blind_id = str(cfg.get("id") or path.stem)
        result = run_single_blind(cfg, use_llm=True, persist_exam=True, persist_benchmark=True)
        result["attempt"] = 1
        result["mode"] = "fresh"
        runs.append(result)

    ok = [r for r in runs if r.get("success")]
    threshold = float(ok[0].get("pass_threshold") or 80) if ok else 80.0
    summaries = []
    by_blind: dict[str, list[dict[str, Any]]] = {}
    for r in runs:
        bid = str(r.get("blind_id") or "")
        by_blind.setdefault(bid, []).append(r)
    for bid, blind_runs in by_blind.items():
        summaries.append(_summarize_blind_runs(bid, blind_runs, threshold=threshold))

    all_scores = [float(r.get("composite") or 0) for r in ok]
    report = {
        "success": all(r.get("passed") for r in ok) if ok else False,
        "agent": AGENT,
        "mode": "fresh",
        "pass_threshold": threshold,
        "recorded_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "overall": {
            "mean_composite": round(sum(all_scores) / max(len(all_scores), 1), 1) if all_scores else 0.0,
            "total_runs": len(ok),
            "total_pass": sum(1 for r in ok if r.get("passed")),
            "total_fail": sum(1 for r in ok if not r.get("passed")),
        },
        "blinds": summaries,
        "runs": runs,
    }
    FRESH_LOG = PROJECT_ROOT / "data" / "blind_exams_fresh_last.json"
    FRESH_LOG.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["backup_path"] = _backup_blind_artifact(FRESH_LOG)
    return report


def notify_blind_report(report: dict[str, Any], *, source: str = "batch") -> dict[str, Any]:
    try:
        from learning_agent.core import telegram_alerts

        return telegram_alerts.alert_blind_batch(report, source=source)
    except Exception as exc:
        return {"sent": False, "detail": str(exc)[:200]}


def main() -> int:
    parser = argparse.ArgumentParser(description="Blind exams finance-lead com resposta fresca")
    parser.add_argument("--blind", action="append", dest="blinds", help="blind_id (repita para varios)")
    parser.add_argument("--no-llm", action="store_true", help="So re-score JSONs existentes")
    parser.add_argument("--batch", type=int, metavar="N", help="Rodar cada blind N vezes e calcular variancia")
    parser.add_argument("--fresh", action="store_true", help="1 run LLM fresco por blind (opcao C)")
    parser.add_argument("--alert", action="store_true", help="Telegram se falhar ou abaixo do limiar")
    parser.add_argument("--consolidate", action="store_true", help="Nota RAG apos batch/fresh")
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if args.fresh:
        report = run_fresh_blinds(blind_ids=args.blinds)
        source = "fresh"
    elif args.batch:
        report = run_batch(repeats=max(1, args.batch), blind_ids=args.blinds)
        source = "batch"
    else:
        report = run_exams(blind_ids=args.blinds, use_llm=not args.no_llm)
        source = "single"

    if args.alert and (report.get("overall") or report.get("blinds")):
        notify_blind_report(report, source=source)

    if args.consolidate and (args.batch or args.fresh):
        from learning_agent.scripts import consolidate_finance_blind_session

        consolidate_finance_blind_session.main()

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
