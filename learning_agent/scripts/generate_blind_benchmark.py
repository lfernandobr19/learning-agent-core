"""Gera benchmark cego semanal — template ou LLM (Groq/Ollama)."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from learning_agent.config import PROJECT_ROOT

BENCHMARKS_ROOT = PROJECT_ROOT / "tests" / "agent_benchmarks"
LOG = PROJECT_ROOT / "data" / "blind_generator_last.json"

STATIC_SCENARIOS = [
    {
        "title": "ITUB4 vs BBDC4 dividendos — fixture only",
        "allowed_tickers": ["ITUB4", "BBDC4", "BOVA11", "PETR4", "VALE3"],
        "scenario": "Comparar yield e risco de ITUB4 vs BBDC4 usando apenas fixtures locais.",
    },
    {
        "title": "WEGE3 acumulacao — dados incompletos",
        "allowed_tickers": ["WEGE3", "BOVA11", "PETR4", "VALE3", "ITUB4"],
        "scenario": "Avaliar entrada em WEGE3 sem preco ao vivo — exigir hold/watch com motivo.",
    },
    {
        "title": "BOVA11 vs carteira stock picking",
        "allowed_tickers": ["BOVA11", "PETR4", "VALE3", "ITUB4", "WEGE3"],
        "scenario": "Decidir entre BOVA11 e 3 acoes individuais com foco em risco agregado.",
    },
]

RUBRIC_TEMPLATE = [
    {"id": "no_invented_prices", "weight": 25, "description": "Declara data_source; nao inventa precos"},
    {"id": "valid_tickers_only", "weight": 20, "description": "So tickers conhecidos"},
    {"id": "risk_section", "weight": 20, "description": "Menciona risco/drawdown/sizing/stop"},
    {"id": "invalidation", "weight": 15, "description": "Criterio de invalidacao explicito"},
    {"id": "no_trade_without_data", "weight": 20, "description": "hold/watch se dados insuficientes"},
]


def _next_blind_id(agent: str) -> str:
    agent_dir = BENCHMARKS_ROOT / agent
    agent_dir.mkdir(parents=True, exist_ok=True)
    nums = []
    for path in agent_dir.glob("blind_*.yaml"):
        m = re.match(r"blind_(\d+)", path.stem)
        if m:
            nums.append(int(m.group(1)))
    n = max(nums, default=0) + 1
    return f"blind_{n:02d}"


def _build_yaml_cfg(agent: str, blind_id: str, scenario: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": blind_id,
        "title": scenario["title"],
        "agent": agent,
        "scorer": "finance_blind_01",
        "pass_threshold": 80,
        "allowed_tickers": scenario["allowed_tickers"],
        "rubric": RUBRIC_TEMPLATE,
        "exam_response_file": f"agents/exams/{agent}_{blind_id}.json",
        "scenario": scenario.get("scenario", ""),
    }


def _try_llm_scenario(agent: str) -> dict[str, Any] | None:
    try:
        from learning_agent.core.llm import chat_with_fallback, is_chat_configured

        if not is_chat_configured():
            return None
        prompt = (
            f"Gere JSON para benchmark cego do agente {agent} (investimento PF Brasil). "
            'Campos: title (string), allowed_tickers (array 5 tickers B3), scenario (string 1 frase). '
            "Sem markdown, so JSON."
        )
        raw, _model = chat_with_fallback(
            [
                {"role": "system", "content": "Responda apenas JSON valido."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=400,
            temperature=0.5,
        )
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```[\w]*\n?", "", cleaned)
            cleaned = re.sub(r"\n?```$", "", cleaned)
        data = json.loads(cleaned)
        if isinstance(data, dict) and data.get("title") and data.get("allowed_tickers"):
            return data
    except Exception:
        return None
    return None


def generate_blind(agent: str = "finance-lead", *, use_llm: bool = True, dry_run: bool = False) -> dict[str, Any]:
    blind_id = _next_blind_id(agent)
    path = BENCHMARKS_ROOT / agent / f"{blind_id}.yaml"
    if path.is_file():
        return {"success": False, "error": f"ja existe: {path}"}

    scenario: dict[str, Any] | None = None
    source = "static"
    if use_llm:
        scenario = _try_llm_scenario(agent)
        if scenario:
            source = "llm"

    if not scenario:
        idx = int(blind_id.split("_")[1]) % len(STATIC_SCENARIOS)
        scenario = STATIC_SCENARIOS[idx]

    cfg = _build_yaml_cfg(agent, blind_id, scenario)
    result = {
        "success": True,
        "agent": agent,
        "blind_id": blind_id,
        "path": str(path.relative_to(PROJECT_ROOT)),
        "source": source,
        "title": cfg["title"],
        "dry_run": dry_run,
    }

    if not dry_run:
        path.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
        exam_path = PROJECT_ROOT / "agents" / "exams" / f"{agent}_{blind_id}.json"
        if not exam_path.is_file():
            exam_path.parent.mkdir(parents=True, exist_ok=True)
            exam_path.write_text(
                json.dumps(
                    {
                        "agent": agent,
                        "blind_id": blind_id,
                        "response": {
                            "data_source": "fixtures locais",
                            "recommendation": "hold",
                            "action": "hold",
                            "tickers": cfg["allowed_tickers"][:2],
                            "risk": "drawdown max 8%, sizing 2% por posicao",
                            "invalidation": "rompimento de suporte com volume",
                        },
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            result["exam_created"] = str(exam_path.relative_to(PROJECT_ROOT))

    result["recorded_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Gerador semanal de benchmark cego")
    parser.add_argument("--agent", default="finance-lead")
    parser.add_argument("--no-llm", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    out = generate_blind(args.agent.strip(), use_llm=not args.no_llm, dry_run=args.dry_run)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
