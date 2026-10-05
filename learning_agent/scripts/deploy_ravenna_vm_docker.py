#!/usr/bin/env python3
"""Deploy Ravenna stack (Docker) to Ravenna VM via SSH."""
from __future__ import annotations

import argparse
import io
import sys
import tarfile
from pathlib import Path

import paramiko

# Windows console defaults to cp1252 — compose output contains UTF-8 (✓, arrows).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]
VM_PROJECT = "/home/{user}/learning-agent"
EXCLUDE_DIRS = {
    ".git",
    ".venv",
    ".venv312",
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
    # Android platform build output (built on the client, not needed on the VM).
    "android",
    ".gradle",
    # Runtime/preserved dirs — never shipped nor clobbered on the VM.
    "data",
    ".vm-backup",
    ".tmp.driveupload",
    "tmp-sync",
}
EXCLUDE_PATH_PARTS = {
    "chroma",
    "test-results",
}
EXCLUDE_SUFFIXES = {".pyc", ".pyo", ".egg-info"}


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


def upload_script(client: paramiko.SSHClient, local: Path, remote: str) -> None:
    text = local.read_text(encoding="utf-8").replace("\r\n", "\n")
    sftp = client.open_sftp()
    with sftp.file(remote, "w") as fh:
        fh.write(text)
    sftp.chmod(remote, 0o755)
    sftp.close()


def should_skip(rel: Path) -> bool:
    parts = rel.parts
    if set(parts) & EXCLUDE_DIRS:
        return True
    if set(parts) & EXCLUDE_PATH_PARTS:
        return True
    name = rel.name
    if name.endswith(".log"):
        return True
    if name.startswith(".env") and name != ".env":
        return True
    return any(name.endswith(s) for s in EXCLUDE_SUFFIXES)


def build_tarball(project_root: Path) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for path in sorted(project_root.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(project_root)
            if should_skip(rel):
                continue
            tar.add(path, arcname=str(rel).replace("\\", "/"))
    buf.seek(0)
    return buf.read()


def docker_env_for_vm(host_ip: str, source_env: Path) -> str:
    """Linux .env for Docker — Groq as LLM (no Ollama/Vast on VM)."""
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
        if raw.strip().startswith("#") or not raw.strip():
            lines.append(raw)
            continue
        lines.append(raw)

    overrides = f"""
# --- Docker VM overrides ---
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
"""
    return "\n".join(lines) + overrides


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="172.26.235.186")
    parser.add_argument("--user", default="<USER>")
    parser.add_argument("--password", required=True)
    parser.add_argument("--skip-upload", action="store_true")
    parser.add_argument("--skip-build", action="store_true", help="Only restart compose")
    args = parser.parse_args()

    vm_dir = VM_PROJECT.format(user=args.user)
    compose_dir = f"{vm_dir}/ravenna-ide"

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"Connecting to {args.user}@{args.host}...")
    client.connect(args.host, username=args.user, password=args.password, timeout=30)

    code, out, err = run(client, "uname -a && free -h && df -h /")
    print("=== VM status ===")
    print(out or err)
    if code != 0:
        print("VM check failed", file=sys.stderr)
        return 1

    docker_script = ROOT / "scripts/vm/debian-docker-ravenna.sh"
    upload_script(client, docker_script, "/tmp/debian-docker-ravenna.sh")
    code, out = sudo(client, args.password, "/tmp/debian-docker-ravenna.sh", timeout=600)
    print("=== Docker install ===", code)
    print(out[-4000:])
    if code != 0:
        return code

    code, out = sudo(client, args.password, f"usermod -aG docker {args.user}")
    print("=== docker group ===", code, out.strip())

    if not args.skip_upload:
        print("Building project tarball (may take a minute)...")
        tarball = build_tarball(ROOT)
        print(f"Tarball size: {len(tarball) / 1024 / 1024:.1f} MB")
        remote_tar = "/tmp/learning-agent.tar.gz"
        sftp = client.open_sftp()
        with sftp.file(remote_tar, "w") as fh:
            fh.write(tarball)
        sftp.close()

        # Preserve VM runtime state (data 22G, .env, .git, oficio mount) via
        # same-filesystem renames (instant — /tmp is tmpfs, do NOT stage there).
        stash = "/home/{user}/.ravenna-deploy-preserve".format(user=args.user)
        run(client, f"rm -rf {stash} && mkdir -p {stash}")
        preserve = [
            ("data", f"{vm_dir}/data"),
            ("dotenv", f"{vm_dir}/.env"),
            ("ide-env", f"{vm_dir}/ravenna-ide/.env"),
            ("git", f"{vm_dir}/.git"),
            ("oficio", f"{vm_dir}/oficio"),
        ]
        for tag, path in preserve:
            run(client, f"mv {path} {stash}/{tag} 2>/dev/null || true")

        run(client, f"rm -rf {vm_dir} && mkdir -p {vm_dir}")
        code, out, err = run(client, f"tar -xzf {remote_tar} -C {vm_dir} && rm -f {remote_tar}", timeout=300)
        print("=== Extract ===", code)
        if code != 0:
            print(out, err, file=sys.stderr)
            return code

        # Restore preserved runtime state on top of the fresh tree.
        run(client, f"mkdir -p {compose_dir}")
        for tag, path in preserve:
            run(client, f"mv {stash}/{tag} {path} 2>/dev/null || true")
        run(client, f"rmdir {stash} 2>/dev/null || true")

    # Keep the VM's existing .env and ravenna-ide/.env (local Ollama + DeepSeek
    # + Groq teacher). Vite uses empty VITE_API_URL → runtime window.location.hostname.

    if args.skip_build:
        compose_inner = "docker compose up -d"
    else:
        compose_inner = "docker compose build --progress=plain && docker compose up -d"

    code, out = sudo(client, args.password, f"cd {compose_dir} && {compose_inner}", timeout=3600)
    print("=== docker compose ===", code)
    print(out[-8000:])

    code2, out2, _ = run(
        client,
        f"curl -sf http://127.0.0.1:8000/health && echo && sudo docker ps --format 'table {{{{.Names}}}}\t{{{{.Status}}}}'",
    )
    print("=== health ===")
    print(out2)

    client.close()
    print(f"\nRavenna VM ready:")
    print(f"  API:      http://{args.host}:8000")
    print(f"  Frontend: http://{args.host}:5173")
    return 0 if code == 0 else code


if __name__ == "__main__":
    raise SystemExit(main())
