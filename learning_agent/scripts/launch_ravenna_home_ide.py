#!/usr/bin/env python3
"""Inicia conversa Agent na IDE Ravenna para o projeto Ravenna Home."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import httpx

API = os.environ.get("RAVENNA_API_BASE", "http://ravenna-vm:8000").rstrip("/")
IDE = os.environ.get("RAVENNA_IDE_URL", "http://ravenna-vm:5173")
OUT = Path(__file__).resolve().parents[2] / "data" / "diagnostics" / "ravenna-home-launch.json"

BRIEF = """\
Projeto **Ravenna Home** — assistente pessoal no celular para a casa do Luis.

## Visão
PWA mobile-first + backend na stack Ravenna. **gemma4-raven** arquiteta e implementa; **raven** é o motor conversacional da app (persona Ravenna, PT-BR). Mesmo pipeline de aprendizado: distillation → ravenna_train.jsonl → few-shots/Modelfile.

## Integrações (MVP extensível)
- Home Assistant (lâmpadas, smart TV, cenários) via REST/WebSocket
- PC do Luis via Tailscale (status Ollama, scripts seguros — sem ações destrutivas)
- Reutilizar `/api/chat` com channel `mobile`

## Entregáveis
1. `ravenna-home/` — backend FastAPI + PWA React/TS
2. Tools/MCP para dispositivos domésticos
3. `agents/curricula/ravenna-home.yaml`
4. Testes pytest + README + `.env.example`
5. Dual-model: estrutura via agent (gemma4-raven), chat usuário via raven

Investigue o repo, diagnostique gaps, implemente solução completa com ```write```/```patch```/```shell```. Não peça confirmação.
"""


def main() -> int:
    timeout = float(os.environ.get("RAVENNA_HOME_TIMEOUT", "3600"))
    client = httpx.Client(timeout=httpx.Timeout(30.0, read=timeout))
    try:
        r = client.post(
            f"{API}/api/chat/conversations",
            params={"channel": "ide"},
            json={
                "title": "Ravenna Home — Assistente Pessoal",
                "project_name": "ravenna-home",
                "project_root": "ravenna-home",
            },
        )
        r.raise_for_status()
        conv = r.json()["conversation"]
        conv_id = conv["id"]
        print(f"Conversa: {conv_id}")
        print(f"IDE: {IDE}")
        print(f"API: {API}/api/chat/conversations")

        payload = {
            "message": BRIEF,
            "mode": "agent",
            "channel": "ide",
            "conversation_id": conv_id,
            "persist_history": True,
            "auto_apply": True,
            "max_repair_attempts": 3,
            "model_size": "32b",
            "project_root": "ravenna-home",
            "run_checklist": True,
        }
        print("Disparando agent autonomy (gemma4-raven)...")
        t0 = time.time()
        run = client.post(f"{API}/api/agent/autonomy/run", json=payload)
        elapsed = round(time.time() - t0, 1)
        result = run.json() if run.headers.get("content-type", "").startswith("application/json") else {"raw": run.text[:2000]}
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(
            json.dumps(
                {
                    "conversation_id": conv_id,
                    "ide_url": IDE,
                    "elapsed_s": elapsed,
                    "status_code": run.status_code,
                    "result": result,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        print(f"Status {run.status_code} em {elapsed}s")
        print(f"Relatório: {OUT}")
        if run.status_code >= 400:
            print(json.dumps(result, indent=2, ensure_ascii=False)[:1500])
            return 1
        autonomy = result.get("autonomy") or {}
        print(f"passed={autonomy.get('passed')} attempts={autonomy.get('attempts')}")
        return 0 if autonomy.get("passed") else 2
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
