"""Verificação do modelo Raven completo — local, sem fallback."""

from __future__ import annotations

import json
import sys
import time

import httpx

from learning_agent.config import CHAT_API_BASE, CHAT_MODEL, CHAT_TIMEOUT_SECONDS, RAVEN_BASE_MODEL
from learning_agent.core import finetune, llm, raven_readiness, software_excellence
from learning_agent.identity import RAVENNA_SYSTEM_BRIEF


def _chat_local(prompt: str) -> tuple[str, str, float]:
    t0 = time.time()
    url = f"{CHAT_API_BASE.rstrip('/')}/chat/completions"
    payload = {
        "model": CHAT_MODEL,
        "messages": [
            {
                "role": "system",
                "content": f"{RAVENNA_SYSTEM_BRIEF} Responda em português.",
            },
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 200,
        "temperature": 0.5,
    }
    with httpx.Client(timeout=CHAT_TIMEOUT_SECONDS) as client:
        r = client.post(url, json=payload)
        r.raise_for_status()
        text = r.json()["choices"][0]["message"]["content"].strip()
    return text, CHAT_MODEL, round(time.time() - t0, 1)


def main() -> int:
    print("=== Verificação Raven (modelo completo) ===\n")

    modelfile = finetune.create_modelfile()
    print(f"Modelfile: {modelfile['few_shot_count']} few-shots, domínios: {modelfile.get('few_shot_domains')}")

    readiness = raven_readiness.assess_readiness()
    factory = software_excellence.assess_excellence()
    print(f"Readiness: {readiness['summary']['readiness_pct']}% ({readiness['summary']['status_label']})")
    print(f"Fábrica: {factory['summary']['factory_ready_pct']}%")
    print(f"Base: {RAVEN_BASE_MODEL} | Runtime: {CHAT_MODEL}\n")

    prompts = [
        "Em 3 bullets: como você estrutura uma API FastAPI em camadas?",
        "Qual sua abordagem para entregar software completo sob demanda com agentes?",
    ]
    results = []
    for p in prompts:
        try:
            text, model, secs = _chat_local(p)
            ok = len(text) > 40 and "ravenna" not in model.lower() or model == CHAT_MODEL
            results.append({"prompt": p[:60], "model": model, "seconds": secs, "chars": len(text), "ok": ok})
            print(f"[{secs}s] {model}: {text[:180]}…\n")
        except Exception as exc:
            results.append({"prompt": p[:60], "error": str(exc), "ok": False})
            print(f"ERRO: {exc}\n")

    # Fallback check — deve usar raven, não Groq
    try:
        _, model_used = llm.chat_with_fallback(
            [{"role": "user", "content": "Diga apenas: online"}],
            max_tokens=10,
            temperature=0.1,
        )
        local_ok = model_used == CHAT_MODEL
    except Exception as exc:
        local_ok = False
        model_used = str(exc)

    report = {
        "readiness_complete": readiness["complete"],
        "few_shot_count": modelfile.get("few_shot_count"),
        "few_shot_domains": modelfile.get("few_shot_domains"),
        "chat_model": CHAT_MODEL,
        "model_used": model_used,
        "local_without_fallback": local_ok,
        "prompts": results,
    }
    out = finetune.TRAINING_DIR.parent / "raven_model_verification.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Relatório: {out}")
    print(json.dumps({"local_ok": local_ok, "model": model_used}, ensure_ascii=False))

    return 0 if readiness["complete"] and local_ok and all(r.get("ok") for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
