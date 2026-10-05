#!/usr/bin/env python3
"""Benchmark lado a lado: raven vs gemma4-coder (Ollama local)."""
from __future__ import annotations

import json
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from learning_agent.core.agent_autonomy_runner import parse_write_blocks
from learning_agent.core.chat import AGENT_SYSTEM

OLLAMA = Path.home() / "AppData/Local/Programs/Ollama/ollama.exe"
OLLAMA_API = "http://127.0.0.1:11434"
MODELS = ("raven", "gemma4-coder")
OUT = Path("data/diagnostics/raven-vs-gemma4-benchmark.json")

CASES: list[dict[str, Any]] = [
    {
        "id": "explain",
        "label": "Explicação (sem write)",
        "user": "Em 3 bullets, explique o que é um endpoint REST em FastAPI.",
        "expects_write": False,
        "max_tokens": 256,
    },
    {
        "id": "write_css",
        "label": "Agent write — CSS",
        "user": (
            "Adicione uma classe `.bench-neon` em cursor-chat.css com borda "
            "1px solid #00ffcc e box-shadow suave. Entregue só com bloco ```write```."
        ),
        "expects_write": True,
        "max_tokens": 512,
    },
    {
        "id": "write_py",
        "label": "Agent write — Python util",
        "user": (
            "Crie `learning_agent/core/bench_slug.py` com função `slugify(text: str) -> str` "
            "que lowercases, troca espaços por hífen e remove chars não alfanuméricos. "
            "Use bloco ```write```."
        ),
        "expects_write": True,
        "max_tokens": 600,
    },
]


def _ollama_ps() -> dict[str, Any]:
    if not OLLAMA.is_file():
        return {}
    try:
        out = subprocess.check_output([str(OLLAMA), "ps"], text=True, timeout=15)
    except Exception as exc:
        return {"error": str(exc)}
    rows = [ln for ln in out.splitlines() if ln.strip() and not ln.startswith("NAME")]
    if not rows:
        return {"loaded": False}
    parts = rows[0].split()
    return {
        "loaded": True,
        "name": parts[0] if parts else "",
        "size": parts[2] if len(parts) > 2 else "",
        "processor": parts[3] if len(parts) > 3 else "",
        "context": parts[4] if len(parts) > 4 else "",
        "raw": rows[0],
    }


def _unload_all() -> None:
    try:
        tags = httpx.get(f"{OLLAMA_API}/api/tags", timeout=10).json()
        for m in tags.get("models", []):
            httpx.post(
                f"{OLLAMA_API}/api/generate",
                json={"model": m["name"], "keep_alive": 0},
                timeout=30,
            )
    except Exception:
        pass
    time.sleep(2)


def _extract_text(data: dict[str, Any]) -> str:
    msg = data.get("message") or {}
    content = msg.get("content") or ""
    if isinstance(content, str) and content.strip():
        return content.strip()
    for key in ("reasoning", "thinking"):
        alt = msg.get(key)
        if isinstance(alt, str) and alt.strip():
            return alt.strip()
    return ""


def _score_write(text: str, *, expects_write: bool) -> dict[str, Any]:
    blocks = parse_write_blocks(text)
    paths = [b.path.strip() for b in blocks]
    valid_fence = len(re.findall(r"```write\s+[^\n`]+", text, re.I))
    prose_only = bool(text.strip()) and not blocks and "```write" not in text.lower()
    score = 0
    notes: list[str] = []
    if expects_write:
        if blocks:
            score += 40
            notes.append(f"{len(blocks)} bloco(s) write parseável(is)")
        if valid_fence:
            score += 20
        if blocks and all(b.content.strip() for b in blocks):
            score += 25
            notes.append("conteúdo não vazio")
        if blocks and all("/" in p or "." in p for p in paths):
            score += 15
        if prose_only:
            score -= 30
            notes.append("só prosa, sem write")
    else:
        if not blocks:
            score += 50
            notes.append("sem write indevido")
        if len(text.strip()) > 40:
            score += 30
            notes.append("resposta substantiva")
        if blocks:
            score -= 20
            notes.append("write desnecessário")
    return {
        "score": max(0, min(100, score)),
        "write_blocks": len(blocks),
        "paths": paths,
        "chars": len(text),
        "notes": notes,
    }


def _run_case(model: str, case: dict[str, Any]) -> dict[str, Any]:
    messages = [
        {"role": "system", "content": AGENT_SYSTEM},
        {"role": "user", "content": case["user"]},
    ]
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"num_predict": case["max_tokens"]},
    }
    t0 = time.perf_counter()
    resp = httpx.post(f"{OLLAMA_API}/api/chat", json=payload, timeout=600.0)
    resp.raise_for_status()
    data = resp.json()
    total_s = time.perf_counter() - t0
    text = _extract_text(data)
    ps = _ollama_ps()
    write = _score_write(text, expects_write=case["expects_write"])
    return {
        "total_s": round(total_s, 2),
        "load_duration_ms": data.get("load_duration", 0) // 1_000_000,
        "eval_duration_ms": data.get("eval_duration", 0) // 1_000_000,
        "prompt_eval_count": data.get("prompt_eval_count"),
        "eval_count": data.get("eval_count"),
        "done_reason": data.get("done_reason"),
        "processor": ps.get("processor", ""),
        "vram_reported": ps.get("size", ""),
        "chars": len(text),
        "preview": text[:400],
        "write_quality": write,
    }


def main() -> int:
    report: dict[str, Any] = {
        "at": datetime.now(timezone.utc).isoformat(),
        "models": MODELS,
        "cases": [c["id"] for c in CASES],
        "results": {},
        "summary": {},
    }
    print("Benchmark raven vs gemma4-coder\n")
    for model in MODELS:
        print(f"=== {model} ===")
        report["results"][model] = {}
        _unload_all()
        model_times: list[float] = []
        model_scores: list[int] = []
        for case in CASES:
            print(f"  {case['id']}...", end=" ", flush=True)
            try:
                row = _run_case(model, case)
                report["results"][model][case["id"]] = row
                model_times.append(row["total_s"])
                model_scores.append(row["write_quality"]["score"])
                print(
                    f"{row['total_s']}s | score {row['write_quality']['score']} | "
                    f"writes {row['write_quality']['write_blocks']} | {row['processor']}"
                )
            except Exception as exc:
                report["results"][model][case["id"]] = {"error": str(exc)}
                print(f"ERR {exc}")
            _unload_all()
        report["summary"][model] = {
            "avg_latency_s": round(sum(model_times) / len(model_times), 2) if model_times else None,
            "avg_quality_score": round(sum(model_scores) / len(model_scores), 1) if model_scores else None,
            "total_latency_s": round(sum(model_times), 2) if model_times else None,
        }
        print()

    # Comparativo
    r = report["summary"].get("raven", {})
    g = report["summary"].get("gemma4-coder", {})
    report["comparison"] = {
        "latency_ratio_gemma_over_raven": (
            round(g["avg_latency_s"] / r["avg_latency_s"], 2)
            if r.get("avg_latency_s") and g.get("avg_latency_s")
            else None
        ),
        "quality_delta_gemma_minus_raven": (
            (g.get("avg_quality_score") or 0) - (r.get("avg_quality_score") or 0)
            if g.get("avg_quality_score") is not None and r.get("avg_quality_score") is not None
            else None
        ),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Relatório: {OUT}")
    print(json.dumps(report["summary"], indent=2))
    print(json.dumps(report["comparison"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
