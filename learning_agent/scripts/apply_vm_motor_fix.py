#!/usr/bin/env python3
"""Passo 1+2: aplica fix workspace /app + tokens na VM (sem rebuild completo)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "learning_agent" / "scripts"))


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.strip().startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())


_load_dotenv(ROOT / ".env")
_load_dotenv(ROOT / "scripts" / "host-gpu.env")

from vm_workspace_registry import host_gpu_registry  # noqa: E402

VM_DIR = "/home/lfernando/learning-agent"
COMPOSE = f"{VM_DIR}/ravenna-ide"
USER = "lfernando"

UPLOAD = (
    "learning_agent/core/workspace_roots.py",
    "learning_agent/core/agent_autonomy_runner.py",
    "learning_agent/core/chat.py",
    "learning_agent/config.py",
    "learning_agent/scripts/vm_workspace_registry.py",
)


def _patch_env_lines(text: str) -> str:
    agent_model = os.environ.get("AGENT_MODEL") or os.environ.get("OLLAMA_MODEL", "gemma4-coder")
    chat_model = os.environ.get("OLLAMA_MODEL_ASSISTANT", "raven")
    tokens = os.environ.get("AGENT_MAX_TOKENS", "3072")
    turns = os.environ.get("AGENT_TOOL_MAX_TURNS", "1")
    strip_prefixes = (
        "RAVENNA_WORKSPACE_ROOT=",
        "RAVENNA_WORKSPACE_PARENT=",
        "AGENT_MAX_TOKENS=",
        "AGENT_TOOL_MAX_TURNS=",
        "AGENT_MODEL=",
        "CHAT_MODEL=",
        "STUDENT_MODEL=",
        "CHAT_TIMEOUT_SECONDS=",
    )
    lines = [line for line in text.splitlines() if not any(line.startswith(p) for p in strip_prefixes)]
    lines.extend(
        [
            "RAVENNA_WORKSPACE_ROOT=/app",
            "RAVENNA_WORKSPACE_PARENT=/app",
            f"AGENT_MAX_TOKENS={tokens}",
            f"AGENT_TOOL_MAX_TURNS={turns}",
            f"AGENT_MODEL={agent_model}",
            f"CHAT_MODEL={chat_model}",
            f"STUDENT_MODEL={agent_model}",
            "CHAT_TIMEOUT_SECONDS=900",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    pwd = os.environ.get("RAVENNA_VM_PASSWORD", "")
    if not pwd:
        print("Defina RAVENNA_VM_PASSWORD", file=sys.stderr)
        return 1
    import paramiko

    host = os.environ.get("RAVENNA_VM_HOST", "ravenna-vm")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, username=USER, password=pwd, timeout=30)
    sftp = client.open_sftp()

    for rel in UPLOAD:
        src = ROOT / rel
        if src.is_file():
            with sftp.file(f"{VM_DIR}/{rel}", "w") as fh:
                fh.write(src.read_text(encoding="utf-8").replace("\r\n", "\n"))

    env_path = f"{VM_DIR}/.env"
    try:
        current = sftp.file(env_path, "r").read().decode("utf-8", errors="replace")
    except OSError:
        current = ""
    with sftp.file(env_path, "w") as fh:
        fh.write(_patch_env_lines(current))

    registry = host_gpu_registry()
    with sftp.file(f"{VM_DIR}/data/ide-workspace-roots.json", "w") as fh:
        fh.write(json.dumps(registry, indent=2, ensure_ascii=False))
    sftp.close()

    compose = f"{VM_DIR}/ravenna-ide"
    stdin, stdout, _ = client.exec_command(
        f"echo {pwd!r} | sudo -S bash -c 'cd {compose} && "
        "docker compose -f docker-compose.yml -f docker-compose.host-gpu.yml up -d backend'",
        timeout=180,
        get_pty=True,
    )
    stdout.read()
    client.close()
    print(
        f"OK — agent={os.environ.get('AGENT_MODEL', 'gemma4-coder')}, "
        f"tokens={os.environ.get('AGENT_MAX_TOKENS', '3072')}, chat.py atualizado, backend reiniciado"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
