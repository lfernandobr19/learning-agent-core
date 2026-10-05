#!/usr/bin/env python3
"""Wire Ravenna VM to Ollama on Windows host (GPU via Tailscale)."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "learning_agent" / "scripts"))

from vm_workspace_registry import host_gpu_registry  # noqa: E402

VM_DIR = "/home/<USER>/learning-agent"
COMPOSE = f"{VM_DIR}/ravenna-ide"
USER = "lfernando"
PWD = os.environ.get("RAVENNA_VM_PASSWORD", "")
GPU_HOST = os.environ.get("RAVENNA_GPU_HOST", "pc-do-luis")
PC_WORKSPACE = os.environ.get(
    "RAVENNA_PC_WORKSPACE",
    r"C:\Users\lfern\RAVENNA\learning-agent\learning-agent",
)
VM_WORKSPACE = "/home/<USER>/workspace-pc"
OLLAMA_PORT = os.environ.get("OLLAMA_PORT", "11434")
ASSISTANT_MODEL = os.environ.get("OLLAMA_MODEL_ASSISTANT", "raven")
MODEL = os.environ.get("OLLAMA_MODEL", "gemma4-raven")
FAST_MODEL = os.environ.get("OLLAMA_MODEL_FAST", "qwen2.5:0.5b")
AGENT_TURNS = os.environ.get("AGENT_TOOL_MAX_TURNS", "3")
AGENT_TOKENS = os.environ.get("AGENT_MAX_TOKENS", "2048")
ACCESS = "ravenna-vm"
OLLAMA_BASE = f"http://{GPU_HOST}:{OLLAMA_PORT}/v1"


def sudo(client, cmd, timeout=600):
    stdin, stdout, _ = client.exec_command(f"sudo -S bash -c {repr(cmd)}", timeout=timeout, get_pty=True)
    stdin.write(PWD + "\n")
    stdin.channel.shutdown_write()
    out = stdout.read().decode("utf-8", errors="replace")
    return stdout.channel.recv_exit_status(), out


def resolve_vm_host() -> str:
    host = os.environ.get("RAVENNA_VM_HOST", "")
    if host:
        return host
    sys.path.insert(0, str(ROOT / "learning_agent" / "scripts"))
    from bootstrap_ravenna_vm import find_host

    return find_host()


def patch_env(source: Path) -> str:
    skip = (
        "LEARNING_DB=", "LOCAL_BACKUP_DIR=", "RAVENNA_WORKSPACE", "CHAT_API_BASE=",
        "CHAT_MODEL=", "CHAT_MODEL_FAST=", "AGENT_MODEL=", "STUDENT_API_BASE=", "IDE_AGENT_USE_LOCAL=",
        "AGENT_TOOL_LOOP=", "AGENT_TOOL_MAX_TURNS=", "AGENT_MAX_TOKENS=",
        "API_HOST=", "STUDENT_MODEL=", "RAVENNA_RUNTIME_BASE=", "CHAT_API_KEY=",
    )
    lines = [l for l in source.read_text(encoding="utf-8").splitlines() if not any(l.startswith(p) for p in skip)]
    lines.append(f"""
# --- VM stack + Ollama GPU no PC ({GPU_HOST}) ---
LEARNING_DB=/app/data
RAVENNA_WORKSPACE_ROOT=/app
RAVENNA_WORKSPACE_PARENT=/app
API_HOST=0.0.0.0
AUTO_AGENT_AUTONOMY=true
AUTONOMY_INTERVAL_SECONDS=1800
IDE_AGENT_USE_LOCAL=true
AGENT_TOOL_LOOP=true
AGENT_TOOL_MAX_TURNS={AGENT_TURNS}
AGENT_MAX_TOKENS={AGENT_TOKENS}
CLOUD_SYNC_ENABLED=false
AUTO_SYNC=false
CHAT_API_BASE={OLLAMA_BASE}
CHAT_MODEL={ASSISTANT_MODEL}
AGENT_MODEL={MODEL}
CHAT_MODEL_FAST={FAST_MODEL}
STUDENT_API_BASE={OLLAMA_BASE}
STUDENT_MODEL={MODEL}
RAVENNA_RUNTIME_BASE={ASSISTANT_MODEL}
CHAT_API_KEY=ollama
CHAT_TIMEOUT_SECONDS=900
CHAT_FAST_MAX_TOKENS=256
TEACHER_API_BASE=https://api.groq.com/openai/v1
RAVENNA_PUBLIC_HOST={ACCESS}
RAVENNA_GPU_HOST={GPU_HOST}
""")
    return "\n".join(lines)


def main() -> int:
    if not PWD:
        print("Defina RAVENNA_VM_PASSWORD", file=sys.stderr)
        return 1

    host = resolve_vm_host()
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"Connecting to {host}...")
    client.connect(host, username=USER, password=PWD, timeout=30)

    # Test Ollama on PC from VM (host + container)
    test_url = f"http://{GPU_HOST}:{OLLAMA_PORT}/api/tags"
    _, out = sudo(client, f"curl -sf --max-time 10 {test_url}", timeout=20)
    if "models" not in out:
        print(
            f"ERRO: VM nao alcanca Ollama em {test_url}\n"
            f"Resposta: {out[:200]!r}\n"
            f"  1) Rode: .\\scripts\\scheduled\\ensure-local-gpu-ollama.ps1\n"
            f"  2) Confirme Tailscale no PC e VM\n"
            f"  3) OLLAMA_HOST=0.0.0.0:{OLLAMA_PORT} no Windows",
            file=sys.stderr,
        )
        client.close()
        return 1
    print(f"VM -> GPU host OK ({GPU_HOST}:{OLLAMA_PORT})")

    import subprocess

    print("Sync PC workspace -> VM (pc-workspace)...")
    sync = subprocess.run(
        [sys.executable, str(ROOT / "learning_agent" / "scripts" / "sync_pc_workspace_to_vm.py")],
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=3600,
    )
    print(sync.stdout[-800:] if sync.stdout else "")
    if sync.returncode != 0:
        print("WARN sync workspace:", (sync.stderr or sync.stdout)[-400:], file=sys.stderr)

    sudo(client, f"mkdir -p {VM_WORKSPACE}", timeout=30)

    sftp = client.open_sftp()
    for rel in (
        "ravenna-ide/docker-compose.yml",
        "ravenna-ide/docker-compose.host-gpu.yml",
        "ravenna-ide/Dockerfile.frontend",
        "ravenna-ide/Dockerfile.backend",
        "learning_agent/api.py",
        "learning_agent/core/chat.py",
        "learning_agent/core/llm.py",
        "learning_agent/core/agent_investigate.py",
        "learning_agent/core/agent_tools.py",
        "learning_agent/core/agent_autonomy_runner.py",
        "learning_agent/config.py",
        "learning_agent/identity.py",
        "learning_agent/core/workspace_roots.py",
        "learning_agent/core/remote_workspace.py",
        "ravenna-ide/frontend/src/utils/resolveComposerMode.ts",
    ):
        with sftp.file(f"{VM_DIR}/{rel}", "w") as fh:
            fh.write((ROOT / rel).read_text(encoding="utf-8").replace("\r\n", "\n"))
    with sftp.file(f"{VM_DIR}/.env", "w") as fh:
        fh.write(patch_env(ROOT / ".env"))
    with sftp.file(f"{COMPOSE}/.env", "w") as fh:
        fh.write(f"VITE_API_URL=http://{ACCESS}:8000\nVITE_WS_URL=ws://{ACCESS}:8000\n")
    registry = host_gpu_registry()
    with sftp.file(f"{VM_DIR}/data/ide-workspace-roots.json", "w") as fh:
        fh.write(json.dumps(registry, indent=2, ensure_ascii=False))
    sftp.close()

    up = (
        f"cd {COMPOSE} && "
        "docker compose -f docker-compose.yml -f docker-compose.host-gpu.yml build backend frontend && "
        "docker compose -f docker-compose.yml -f docker-compose.host-gpu.yml up -d --force-recreate"
    )
    print("Subindo stack (sem Ollama na VM)...")
    code, out = sudo(client, up, timeout=600)
    print(out[-2500:].encode("ascii", errors="replace").decode())
    if code != 0:
        client.close()
        return code

    sudo(client, "docker stop ravenna-ollama 2>/dev/null; docker rm ravenna-ollama 2>/dev/null; true", timeout=60)

    print("Restart backend...")
    sudo(client, f"cd {COMPOSE} && docker compose up -d --force-recreate backend", timeout=300)

    raw = ""
    for _ in range(24):
        stdin, stdout, _ = client.exec_command("curl -sf http://127.0.0.1:8000/health", timeout=30)
        raw = stdout.read().decode("utf-8", errors="replace")
        if "total_notes" in raw:
            break
        time.sleep(5)
    print(raw.encode("ascii", errors="replace").decode()[-800:])

    stdin, stdout, _ = client.exec_command(
        "docker exec ravenna-backend python -c "
        "\"from learning_agent.core import llm; "
        "print(llm.chat_with_fallback([{'role':'user','content':'diga ok'}], "
        f"model='{FAST_MODEL}', max_tokens=16))\"",
        timeout=300,
    )
    stdout.channel.settimeout(300)
    chat = stdout.read().decode("utf-8", errors="replace")
    print("fast llm:", chat[:200].encode("ascii", errors="replace").decode())
    if FAST_MODEL not in chat and "qwen" not in chat.lower():
        print("WARN: inferencia fast nao retornou qwen — confira Ollama no PC", file=sys.stderr)

    stdin, stdout, _ = client.exec_command(
        "curl -sf -m 120 -X POST http://127.0.0.1:8000/api/chat -H 'Content-Type: application/json' "
        '-d \'{"message":"oi","model_size":"0.5b"}\'',
        timeout=180,
    )
    stdout.channel.settimeout(180)
    api_chat = stdout.read().decode("utf-8", errors="replace")
    print("api chat:", api_chat[:300].encode("ascii", errors="replace").decode())
    if FAST_MODEL not in api_chat and "qwen" not in api_chat.lower():
        print("WARN: API ainda pode estar no fallback Groq — confira Ollama no PC", file=sys.stderr)

    client.close()
    print(
        f"\nPronto — remoto: http://{ACCESS}:5173"
        f"\n  LLM: {OLLAMA_BASE}"
        f"\n  assistente: {ASSISTANT_MODEL} | agente: {MODEL} | fast: {FAST_MODEL}"
        f"\n  VM sem Ollama local (RAM liberada)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
