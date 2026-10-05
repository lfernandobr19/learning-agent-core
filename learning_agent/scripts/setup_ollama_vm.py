#!/usr/bin/env python3
"""Deploy Ollama on Ravenna VM: 7b brain + 0.5b fast (GPU when available)."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parents[2]
VM_DIR = "/home/<USER>/learning-agent"
COMPOSE = f"{VM_DIR}/ravenna-ide"
HOST = os.environ.get("RAVENNA_VM_HOST", "ravenna-vm")
USER = "lfernando"
PWD = os.environ.get("RAVENNA_VM_PASSWORD", "")
MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")
FAST_MODEL = os.environ.get("OLLAMA_MODEL_FAST", "qwen2.5:0.5b")
USE_GPU = os.environ.get("OLLAMA_USE_GPU", "auto").lower()  # auto | true | false
ACCESS = "ravenna-vm"


def sudo(client, cmd, timeout=3600):
    stdin, stdout, _ = client.exec_command(f"sudo -S bash -c {repr(cmd)}", timeout=timeout, get_pty=True)
    stdin.write(PWD + "\n")
    stdin.channel.shutdown_write()
    out = stdout.read().decode("utf-8", errors="replace")
    return stdout.channel.recv_exit_status(), out


def patch_env(source: Path) -> str:
    skip = (
        "LEARNING_DB=", "LOCAL_BACKUP_DIR=", "RAVENNA_WORKSPACE", "CHAT_API_BASE=",
        "CHAT_MODEL=", "CHAT_MODEL_FAST=", "STUDENT_API_BASE=", "IDE_AGENT_USE_LOCAL=",
        "API_HOST=", "TEACHER_", "STUDENT_MODEL=", "RAVENNA_RUNTIME_BASE=",
    )
    lines = [l for l in source.read_text(encoding="utf-8").splitlines() if not any(l.startswith(p) for p in skip)]
    lines.append(f"""
# --- VM Ollama dual: {MODEL} (cérebro) + {FAST_MODEL} (rápido) ---
LEARNING_DB=/app/data
RAVENNA_WORKSPACE_ROOT=/app
RAVENNA_WORKSPACE_PARENT=/app
API_HOST=0.0.0.0
AUTO_AGENT_AUTONOMY=true
AUTONOMY_INTERVAL_SECONDS=1800
IDE_AGENT_USE_LOCAL=true
CLOUD_SYNC_ENABLED=false
AUTO_SYNC=false
CHAT_API_BASE=http://ollama:11434/v1
CHAT_MODEL={MODEL}
CHAT_MODEL_FAST={FAST_MODEL}
STUDENT_API_BASE=http://ollama:11434/v1
STUDENT_MODEL={MODEL}
RAVENNA_RUNTIME_BASE={MODEL}
CHAT_API_KEY=ollama
CHAT_TIMEOUT_SECONDS=600
CHAT_FAST_MAX_TOKENS=256
TEACHER_API_BASE=https://api.groq.com/openai/v1
RAVENNA_PUBLIC_HOST={ACCESS}
""")
    return "\n".join(lines)


def vm_has_gpu(client) -> bool:
    _, out = sudo(client, "nvidia-smi -L 2>/dev/null | head -1", timeout=20)
    return "GPU" in out


def compose_up_cmd(gpu: bool) -> str:
    if gpu:
        return (
            f"cd {COMPOSE} && docker compose --profile vm-ollama "
            f"-f docker-compose.yml -f docker-compose.gpu.yml up -d"
        )
    return f"cd {COMPOSE} && docker compose pull ollama && docker compose --profile vm-ollama up -d"


def main() -> int:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"Connecting to {HOST}...")
    client.connect(HOST, username=USER, password=PWD, timeout=30)

    gpu = USE_GPU == "true"
    if USE_GPU == "auto":
        gpu = vm_has_gpu(client)
    print(f"GPU compose: {'sim' if gpu else 'nao (CPU only — 0.5b ainda funciona, so mais lento)'}")

    _, mem = sudo(client, "free -h | head -2", timeout=30)
    print(mem.encode("ascii", errors="replace").decode())

    sftp = client.open_sftp()
    for rel in (
        "ravenna-ide/docker-compose.yml",
        "ravenna-ide/docker-compose.gpu.yml",
        "learning_agent/scripts/install_nvidia_container_vm.sh",
    ):
        local = ROOT / rel
        remote = f"{VM_DIR}/{rel.replace(chr(92), '/')}"
        with sftp.file(remote, "w") as fh:
            fh.write(local.read_text(encoding="utf-8").replace("\r\n", "\n"))
    with sftp.file(f"{COMPOSE}/docker-compose.yml", "w") as fh:
        fh.write((ROOT / "ravenna-ide/docker-compose.yml").read_text(encoding="utf-8").replace("\r\n", "\n"))
    with sftp.file(f"{VM_DIR}/.env", "w") as fh:
        fh.write(patch_env(ROOT / ".env"))
    with sftp.file(f"{COMPOSE}/.env", "w") as fh:
        fh.write(f"VITE_API_URL=http://{ACCESS}:8000\nVITE_WS_URL=ws://{ACCESS}:8000\n")
    sftp.close()

    if gpu:
        print("Verificando nvidia-container-toolkit...")
        code, out = sudo(
            client,
            "docker run --rm --gpus all nvidia/cuda:12.2.0-base-ubuntu22.04 nvidia-smi -L 2>&1 | head -2",
            timeout=120,
        )
        if code != 0 or "GPU" not in out:
            print("nvidia-container-toolkit ausente — instalando...")
            sudo(client, f"chmod +x {VM_DIR}/learning_agent/scripts/install_nvidia_container_vm.sh", timeout=10)
            code, out = sudo(
                client,
                f"bash {VM_DIR}/learning_agent/scripts/install_nvidia_container_vm.sh",
                timeout=600,
            )
            print(out[-2000:].encode("ascii", errors="replace").decode())
            if code != 0:
                print("WARN: toolkit install failed; subindo sem GPU", file=sys.stderr)
                gpu = False

    print("Starting Ollama + stack...")
    code, out = sudo(client, compose_up_cmd(gpu), timeout=600)
    print(out[-3000:].encode("ascii", errors="replace").decode())
    if code != 0:
        return code

    for tag in (FAST_MODEL, MODEL):
        print(f"Pulling {tag}...")
        code, out = sudo(client, f"docker exec ravenna-ollama ollama pull {tag}", timeout=3600)
        print(out[-1500:].encode("ascii", errors="replace").decode())
        if code != 0:
            print(f"WARN: pull {tag} failed", file=sys.stderr)

    # Warm fast model on GPU when available
    warm = f'docker exec ravenna-ollama ollama run {FAST_MODEL} "ok" --verbose 2>&1 | tail -5'
    print(f"Warming {FAST_MODEL}...")
    sudo(client, warm, timeout=300)

    print("Restarting backend...")
    sudo(client, f"cd {COMPOSE} && docker compose up -d --force-recreate backend", timeout=300)

    raw = ""
    for _ in range(20):
        stdin, stdout, _ = client.exec_command(
            "curl -sf http://127.0.0.1:8000/health && docker exec ravenna-ollama ollama list",
            timeout=30,
        )
        raw = stdout.read().decode("utf-8", errors="replace")
        if "total_notes" in raw:
            break
        time.sleep(5)

    print(raw.encode("ascii", errors="replace").decode()[-1500:])

    stdin, stdout, _ = client.exec_command(
        "curl -sf -X POST http://127.0.0.1:8000/api/chat -H 'Content-Type: application/json' "
        '-d \'{"message":"oi","model_size":"0.5b"}\' | head -c 400',
        timeout=180,
    )
    chat = stdout.read().decode("utf-8", errors="replace")
    print("fast chat test:", chat[:250].encode("ascii", errors="replace").decode())

    client.close()
    print(
        f"\nPronto: http://{ACCESS}:5173"
        f"\n  cerebro={MODEL}  |  rapido={FAST_MODEL}  |  gpu={'sim' if gpu else 'nao'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
