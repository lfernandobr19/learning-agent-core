#!/usr/bin/env python3
"""Validacao final do stack unificado + consulta Ravenna."""
from __future__ import annotations

import json
import os
import sys

import httpx

BASE = os.environ.get("RAVENNA_API_BASE", "http://ravenna-vm:8000").rstrip("/")
CHECKS: list[tuple[str, str, int]] = []


def ok(name: str, passed: bool, detail: str = "") -> None:
    CHECKS.append((name, "OK" if passed else "FAIL", detail))
    mark = "OK" if passed else "FAIL"
    print(f"[{mark}] {name}" + (f" — {detail}" if detail else ""))


def main() -> int:
    with httpx.Client(timeout=120, base_url=BASE) as c:
        r = c.get("/health")
        ok("API health", r.status_code == 200 and r.json().get("status") == "ok")

        roots = c.get("/api/workspace/roots").json()
        primary = roots.get("primary_id", "")
        ok("Workspace PC sync", primary == "pc-workspace", primary)

        files = c.get("/api/files", params={"path": ""}).json()
        ok("Explorer arquivos", len(files.get("entries", [])) > 0, f"{len(files.get('entries', []))} entradas")

        parity = c.get("/api/ide/parity").json()
        ok("Paridade IDE", parity.get("ok") or parity.get("score", 0) >= 9, f"{parity.get('score')}/{parity.get('total')}")

        auto = c.get("/api/agents/autonomy/always-on").json()
        prefs = auto.get("prefs") or {}
        always = bool(prefs.get("always_on") or auto.get("always_on_persisted"))
        ok("Autonomia always_on", always, str(prefs))

        dist = c.get("/api/distillation/status").json()
        student = (dist.get("student") or {}).get("model", "")
        ok("LLM student", "raven" in student or "qwen" in student, student)

        chat = c.post(
            "/api/chat",
            json={
                "message": (
                    "Ravenna, confirme em pelo menos três frases completas: "
                    "stack unificado VM+PC ativo, workspace PC sync, Telegram, "
                    "autonomia always_on e modelo raven como student."
                ),
                "mode": "chat",
                "model_size": "0.5b",
                "channel": "ide",
            },
        )
        body = chat.json() if chat.status_code == 200 else {}
        msg = body.get("message", "")
        ok("Chat Ravenna", chat.status_code == 200 and len(msg.strip()) > 40, msg[:100].encode("ascii", "replace").decode())

        remote = c.get("/api/workspace/remote/profiles").json()
        profiles = remote.get("profiles") or []
        ok("SSH live profile", any(p.get("id") == "pc-live" for p in profiles), f"{len(profiles)} perfis")

    failed = sum(1 for _, s, _ in CHECKS if s == "FAIL")
    print(f"\n{'TUDO OK' if failed == 0 else f'{failed} FALHA(S)'} — {len(CHECKS)} checks")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
