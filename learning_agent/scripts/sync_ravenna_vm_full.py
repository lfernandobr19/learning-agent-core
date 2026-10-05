#!/usr/bin/env python3
"""Full sync Learning Agent + Ravenna memory to VM + Tailscale remote access."""
from __future__ import annotations

import argparse
import io
import os
import re
import sys
import tarfile
import time
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parents[2]
VM_PROJECT = "/home/{user}/learning-agent"
COMPOSE = "/home/{user}/learning-agent/ravenna-ide"

# Full sync: keep data/chroma and docs; skip only rebuild artifacts
EXCLUDE_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    ".cursor",
    "dist",
    "build",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "test-results",
    "e2e",
}
EXCLUDE_SUFFIXES = {".pyc", ".pyo"}


def run(client: paramiko.SSHClient, cmd: str, *, timeout: int = 600) -> tuple[int, str, str]:
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout, get_pty=True)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    return stdout.channel.recv_exit_status(), out, err


def sudo(client: paramiko.SSHClient, password: str, cmd: str, *, timeout: int = 900) -> tuple[int, str]:
    stdin, stdout, stderr = client.exec_command(f"sudo -S bash -c {repr(cmd)} 2>&1", timeout=timeout, get_pty=True)
    stdin.write(password + "\n")
    stdin.channel.shutdown_write()
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    return stdout.channel.recv_exit_status(), out + err


def should_skip(rel: Path) -> bool:
    if set(rel.parts) & EXCLUDE_DIRS:
        return True
    name = rel.name
    if name.startswith(".env") and name != ".env":
        return True
    if name.endswith(".log") and "data" in rel.parts and "scheduled" in rel.parts:
        return True
    return any(name.endswith(s) for s in EXCLUDE_SUFFIXES)


def build_tarball(project_root: Path) -> bytes:
    buf = io.BytesIO()
    count = 0
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for path in sorted(project_root.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(project_root)
            if should_skip(rel):
                continue
            tar.add(path, arcname=str(rel).replace("\\", "/"))
            count += 1
    print(f"Tarball: {count} files")
    buf.seek(0)
    return buf.read()


def docker_env_for_vm(public_host: str, source_env: Path) -> str:
    lines: list[str] = []
    skip_prefixes = (
        "LEARNING_DB=",
        "LOCAL_BACKUP_DIR=",
        "RAVENNA_WORKSPACE",
        "CHAT_API_BASE=",
        "CHAT_MODEL=",
        "CHAT_MODEL_FAST=",
        "STUDENT_API_BASE=",
        "IDE_AGENT_USE_LOCAL=",
        "API_HOST=",
    )
    for raw in source_env.read_text(encoding="utf-8").splitlines():
        if any(raw.startswith(p) for p in skip_prefixes):
            continue
        lines.append(raw)

    overrides = f"""
# --- VM Docker (Tailscale host: {public_host}) ---
LEARNING_DB=/app/data
API_HOST=0.0.0.0
CLOUD_SYNC_ENABLED=false
AUTO_SYNC=false
AUTO_AGENT_AUTONOMY=false
IDE_AGENT_USE_LOCAL=false
CHAT_API_BASE=https://api.groq.com/openai/v1
CHAT_MODEL=llama-3.3-70b-versatile
CHAT_MODEL_FAST=llama-3.3-70b-versatile
STUDENT_API_BASE=https://api.groq.com/openai/v1
RAVENNA_PUBLIC_HOST={public_host}
"""
    return "\n".join(lines) + overrides


def tailscale_public_host(
    client: paramiko.SSHClient, password: str, auth_key: str | None
) -> tuple[str, str | None]:
    """Return (access_host, login_url_or_none)."""
    code, out, _ = run(client, "tailscale ip -4 2>/dev/null; tailscale status 2>/dev/null | head -5")
    m = re.search(r"\b(100\.\d+\.\d+\.\d+)\b", out)
    if m:
        ip = m.group(1)
        print(f"Tailscale already up: {ip}")
        return "ravenna-vm", None

    up_cmd = "tailscale up --hostname=ravenna-vm --accept-dns=true --reset"
    if auth_key:
        up_cmd += f" --auth-key={auth_key}"

    print("Starting Tailscale...")
    _, out = sudo(client, password, up_cmd, timeout=180)
    print(out[-2500:])

    for _ in range(18):
        _, out, _ = run(client, "tailscale ip -4 2>/dev/null")
        ip = out.strip().split()[-1] if out.strip() else ""
        if ip.startswith("100."):
            print(f"Tailscale IP: {ip}")
            return "ravenna-vm", None
        time.sleep(5)

    login = re.search(r"https://login\.tailscale\.com/[^\s\x1b]+", out)
    login_url = login.group(0) if login else None
    if login_url:
        print(f"\n>>> Login Tailscale (uma vez): {login_url}\n")
    return "ravenna-vm", login_url


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="172.26.235.186")
    parser.add_argument("--user", default="lfernando")
    parser.add_argument("--password", required=True)
    parser.add_argument("--tailscale-auth-key", default=os.environ.get("TAILSCALE_AUTH_KEY", ""), help="tskey-auth-...")
    parser.add_argument("--skip-upload", action="store_true")
    parser.add_argument("--skip-build", action="store_true")
    args = parser.parse_args()

    vm_dir = VM_PROJECT.format(user=args.user)
    compose_dir = COMPOSE.format(user=args.user)
    auth_key = args.tailscale_auth_key.strip() or None

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"Connecting to {args.user}@{args.host}...")
    client.connect(args.host, username=args.user, password=args.password, timeout=30)

    code, out, _ = run(client, "free -h; df -h /; docker ps --format '{{.Names}} {{.Status}}' 2>/dev/null || true")
    print("=== VM ===\n", out)

    public_host, tailscale_login = tailscale_public_host(client, args.password, auth_key)
    access_host = public_host

    _, ts_ip_out, _ = run(client, "tailscale ip -4 2>/dev/null")
    tailscale_ip = next((p for p in ts_ip_out.split() if p.startswith("100.")), "")

    if not args.skip_upload:
        print("Building full tarball (data + chroma + docs)...")
        tarball = build_tarball(ROOT)
        mb = len(tarball) / 1024 / 1024
        print(f"Uploading {mb:.1f} MB...")
        remote_tar = "/tmp/learning-agent-full.tar.gz"
        sftp = client.open_sftp()
        with sftp.file(remote_tar, "w") as fh:
            chunk = 1024 * 1024
            for i in range(0, len(tarball), chunk):
                fh.write(tarball[i : i + chunk])
        sftp.close()

        sudo(client, args.password, f"cd {compose_dir} && docker compose down 2>/dev/null || true", timeout=120)
        run(client, f"rm -rf {vm_dir} && mkdir -p {vm_dir}")
        code, out, err = run(client, f"tar -xzf {remote_tar} -C {vm_dir} && rm -f {remote_tar}", timeout=1800)
        print("=== Extract ===", code)
        if code != 0:
            print(out, err, file=sys.stderr)
            return code

    env_text = docker_env_for_vm(access_host, ROOT / ".env")
    compose_env = (
        f"VITE_API_URL=http://{access_host}:8000\n"
        f"VITE_WS_URL=ws://{access_host}:8000\n"
    )
    sftp = client.open_sftp()
    with sftp.file(f"{compose_dir}/.env", "w") as fh:
        fh.write(compose_env)
    with sftp.file(f"{vm_dir}/.env", "w") as fh:
        fh.write(env_text)
    sftp.close()

    if args.skip_build:
        inner = "docker compose up -d"
    else:
        inner = "docker compose build --progress=plain && docker compose up -d"

    code, out = sudo(client, args.password, f"cd {compose_dir} && {inner}", timeout=7200)
    print("=== compose ===", code)
    print(out[-6000:])

    _, health, _ = run(
        client,
        "curl -sf http://127.0.0.1:8000/health | python3 -c \"import sys,json; d=json.load(sys.stdin); print('notes', d.get('learning',{}).get('total_notes')); print('status', d.get('status'))\" 2>/dev/null || curl -sf http://127.0.0.1:8000/health",
    )
    print("=== health ===\n", health)
    _, ps, _ = run(client, "sudo docker ps --format 'table {{.Names}}\t{{.Status}}'")

    client.close()
    login_line = f"\n  Login (uma vez): {tailscale_login}" if tailscale_login else ""
    ip_line = f"\n  Tailscale IP:  http://{tailscale_ip}:5173" if tailscale_ip else ""
    print(
        f"""
=== Ravenna remota (Tailscale) ===
  MagicDNS:      http://{access_host}:5173
  API:           http://{access_host}:8000{ip_line}{login_line}

De outra rede (celular/notebook):
  1. Instale Tailscale (mesma conta Google/Microsoft)
  2. Ative MagicDNS em https://login.tailscale.com/admin/dns
  3. Abra http://{access_host}:5173
"""
    )
    return 0 if code == 0 else code


if __name__ == "__main__":
    raise SystemExit(main())
