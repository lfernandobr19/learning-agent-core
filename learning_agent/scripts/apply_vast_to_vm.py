#!/usr/bin/env python3
"""Aponta VM para Ollama na Vast (IP público) — overnight sem túnel no PC."""
from __future__ import annotations

import json
import os
import sys
import time
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
_load_dotenv(ROOT / "scripts" / "vast-overnight.env")
_load_dotenv(ROOT / "scripts" / "vast-host.env")

VM_DIR = "/home/<USER>/learning-agent"
USER = "lfernando"

UPLOAD = (
    "learning_agent/core/chat.py",
    "learning_agent/scripts/vast_overnight_runtime.py",
    "learning_agent/scripts/run_vast_overnight_motor.py",
    "learning_agent/scripts/run_motor_diagnostic.py",
    "learning_agent/scripts/apply_vast_to_vm.py",
    "scripts/vast-overnight.env",
    "ravenna-ide/docker-compose.host-gpu.yml",
)


def _patch_env(text: str, *, ollama_base: str, vast_host: str, agent_model: str, chat_model: str) -> str:
    ollama = f"{ollama_base.rstrip('/')}/v1"
    tokens = os.environ.get("VAST_OVERNIGHT_AGENT_TOKENS", "4096")
    turns = os.environ.get("VAST_OVERNIGHT_AGENT_TURNS", "2")
    strip = (
        "CHAT_API_BASE=",
        "STUDENT_API_BASE=",
        "AGENT_MODEL=",
        "CHAT_MODEL=",
        "STUDENT_MODEL=",
        "AGENT_MAX_TOKENS=",
        "AGENT_TOOL_MAX_TURNS=",
        "RAVENNA_GPU_HOST=",
        "IDE_AGENT_USE_LOCAL=",
        "TEACHER_API_KEY=",
        "TEACHER_API_BASE=",
        "TEACHER_MODEL=",
        "VAST_OVERNIGHT_BUDGET_USD=",
        "VAST_HOURLY_USD=",
        "VAST_CREDIT_USD=",
        "VAST_HOST=",
        "VAST_SSH_PORT=",
        "VAST_INSTANCE_ID=",
        "VAST_OVERNIGHT_READ_TIMEOUT=",
        "VAST_OVERNIGHT_MODEL_SIZE=",
    )
    lines = [ln for ln in text.splitlines() if not any(ln.startswith(p) for p in strip)]
    lines.extend(
        [
            f"CHAT_API_BASE={ollama}",
            f"STUDENT_API_BASE={ollama}",
            f"AGENT_MODEL={agent_model}",
            f"STUDENT_MODEL={agent_model}",
            f"CHAT_MODEL={chat_model}",
            "CHAT_API_KEY=ollama",
            f"AGENT_MAX_TOKENS={tokens}",
            f"AGENT_TOOL_MAX_TURNS={turns}",
            "IDE_AGENT_USE_LOCAL=true",
            "TEACHER_API_KEY=",
            "TEACHER_API_BASE=",
            f"RAVENNA_GPU_HOST={vast_host}",
            "CHAT_TIMEOUT_SECONDS=3600",
            f"VAST_OVERNIGHT_BUDGET_USD={os.environ.get('VAST_OVERNIGHT_BUDGET_USD', '5')}",
            f"VAST_HOURLY_USD={os.environ.get('VAST_HOURLY_USD', '0.012')}",
            f"VAST_CREDIT_USD={os.environ.get('VAST_CREDIT_USD', '8')}",
            f"VAST_HOST={vast_host}",
            f"VAST_SSH_PORT={os.environ.get('VAST_SSH_PORT', '8263')}",
            f"VAST_OLLAMA_PORT={os.environ.get('VAST_OLLAMA_PORT', '11435')}",
            f"VAST_OLLAMA_LOCAL_PORT={os.environ.get('VAST_OLLAMA_LOCAL_PORT', os.environ.get('VAST_OLLAMA_PORT', '11435'))}",
            f"VAST_INSTANCE_ID={os.environ.get('VAST_INSTANCE_ID', '')}",
            f"VAST_OVERNIGHT_READ_TIMEOUT={os.environ.get('VAST_OVERNIGHT_READ_TIMEOUT', '3600')}",
            f"VAST_OVERNIGHT_MODEL_SIZE={os.environ.get('VAST_OVERNIGHT_MODEL_SIZE', '32b')}",
        ]
    )
    return "\n".join(lines) + "\n"


def _setup_vm_tunnel(client, *, vast_host: str, ssh_port: int, key_path: Path) -> str:
    """SSH tunnel VM host -> Vast Ollama; docker usa host.docker.internal."""
    remote_key = f"{VM_DIR}/.ssh/vast_overnight_key"
    local_port = os.environ.get("VAST_OLLAMA_LOCAL_PORT") or os.environ.get("VAST_OLLAMA_PORT", "11435")
    remote_port = os.environ.get("VAST_OLLAMA_REMOTE_PORT", "11434")
    client.exec_command(f"mkdir -p {VM_DIR}/.ssh && chmod 700 {VM_DIR}/.ssh", timeout=30)
    sftp = client.open_sftp()
    sftp.put(str(key_path), remote_key)
    sftp.chmod(remote_key, 0o600)
    sftp.close()
    kill_all = f"pkill -f 'ssh.*{vast_host}' || true"
    kill = f"pkill -f 'ssh.*{vast_host}.*{local_port}:127.0.0.1:{remote_port}' || true"
    tunnel = (
        f"ssh -f -N -o StrictHostKeyChecking=no -o ServerAliveInterval=30 "
        f"-i {remote_key} -p {ssh_port} -L 0.0.0.0:{local_port}:127.0.0.1:{remote_port} "
        f"root@{vast_host}"
    )
    client.exec_command(kill_all, timeout=15)
    time.sleep(1)
    client.exec_command(kill, timeout=15)
    time.sleep(1)
    _, stdout, stderr = client.exec_command(tunnel, timeout=30)
    stdout.channel.recv_exit_status()
    err = stderr.read().decode("utf-8", errors="replace").strip()
    iptables = (
        f"iptables -C INPUT -p tcp --dport {local_port} -j ACCEPT 2>/dev/null || "
        f"iptables -I INPUT -p tcp --dport {local_port} -j ACCEPT"
    )
    client.exec_command(f"echo {os.environ.get('RAVENNA_VM_PASSWORD', '')!r} | sudo -S bash -c {iptables!r}", timeout=20)
    verify = (
        f"curl -sf -m 8 http://127.0.0.1:{local_port}/api/tags >/dev/null && echo OK"
    )
    _, vout, _ = client.exec_command(verify, timeout=20)
    if b"OK" in vout.read():
        return f"http://host.docker.internal:{local_port}"
    if err and "Warning" not in err:
        raise RuntimeError(f"tunnel falhou: {err}")
    raise RuntimeError(f"tunnel inacessivel na porta {local_port}")


def main() -> int:
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--vast-host", default=os.environ.get("VAST_HOST", ""))
    p.add_argument("--agent-model", default=os.environ.get("VAST_OVERNIGHT_AGENT_MODEL", "qwen2.5:32b"))
    p.add_argument("--no-tunnel", action="store_true", help="Ollama exposto no IP publico (sem SSH tunnel)")
    args = p.parse_args()
    if not args.vast_host:
        print("Defina VAST_HOST ou --vast-host", file=sys.stderr)
        return 1

    pwd = os.environ.get("RAVENNA_VM_PASSWORD", "")
    if not pwd:
        print("Defina RAVENNA_VM_PASSWORD", file=sys.stderr)
        return 1

    import paramiko

    host = os.environ.get("RAVENNA_VM_HOST", "ravenna-vm")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, username=USER, password=pwd, timeout=30)

    ssh_port = int(os.environ.get("VAST_SSH_PORT", "22"))
    key_path = Path(os.environ.get("VAST_SSH_KEY", Path.home() / ".ssh" / "id_ed25519"))
    if args.no_tunnel:
        ollama_base = f"http://{args.vast_host}:{os.environ.get('VAST_OLLAMA_PORT', '11434')}"
    else:
        if not key_path.is_file():
            print(f"Chave SSH ausente: {key_path}", file=sys.stderr)
            return 1
        ollama_base = _setup_vm_tunnel(client, vast_host=args.vast_host, ssh_port=ssh_port, key_path=key_path)

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
        fh.write(_patch_env(
            current,
            ollama_base=ollama_base,
            vast_host=args.vast_host,
            agent_model=args.agent_model,
            chat_model=os.environ.get("VAST_OVERNIGHT_CHAT_MODEL", "gemma4-raven"),
        ))
    sftp.close()

    compose = f"{VM_DIR}/ravenna-ide"
    cmd = (
        f"cd {compose} && docker compose -f docker-compose.yml -f docker-compose.host-gpu.yml "
        "up -d backend"
    )
    stdin, stdout, _ = client.exec_command(
        f"echo {pwd!r} | sudo -S bash -c {cmd!r}",
        timeout=180,
        get_pty=True,
    )
    out = stdout.read().decode("utf-8", errors="replace")
    client.close()
    print(f"OK — VM -> {ollama_base}/v1 agent={args.agent_model}")
    if out.strip():
        print(out[-500:].encode("ascii", errors="replace").decode("ascii"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
