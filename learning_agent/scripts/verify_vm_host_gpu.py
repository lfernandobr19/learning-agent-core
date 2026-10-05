#!/usr/bin/env python3
"""Quick verify VM -> PC Ollama + backend chat."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "learning_agent" / "scripts"))
from bootstrap_ravenna_vm import find_host  # noqa: E402

PWD = os.environ.get("RAVENNA_VM_PASSWORD", "")
GPU_HOST = os.environ.get("RAVENNA_GPU_HOST", "pc-do-luis")
FAST = os.environ.get("OLLAMA_MODEL_FAST", "qwen2.5:0.5b")


def run(client: paramiko.SSHClient, cmd: str, timeout: int = 120) -> tuple[int, str, str]:
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    return stdout.channel.recv_exit_status(), out, err


def main() -> int:
    if not PWD:
        print("Defina RAVENNA_VM_PASSWORD", file=sys.stderr)
        return 1

    host = os.environ.get("RAVENNA_VM_HOST") or find_host()
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"Connecting to {host}...")
    client.connect(host, username="lfernando", password=PWD, timeout=30)

    code, out, err = run(client, f"curl -sf --max-time 10 http://{GPU_HOST}:11434/api/tags", 20)
    print("tags:", "OK" if "models" in out else out[:200])
    if "models" not in out:
        return 1

    py = (
        "from learning_agent.core import llm; "
        "print(llm.chat_with_fallback("
        "[{'role':'user','content':'diga ok'}], "
        f"model='{FAST}', max_tokens=16))"
    )
    code, out, err = run(
        client,
        f"docker exec ravenna-backend python -c {py!r}",
        timeout=300,
    )
    print("fast llm:", out.strip()[:300] or err[:300])
    if not out.strip():
        return 1

    code, out, err = run(
        client,
        "curl -sf -m 120 -X POST http://127.0.0.1:8000/api/chat "
        "-H 'Content-Type: application/json' "
        '-d \'{"message":"oi","model_size":"0.5b"}\'',
        timeout=180,
    )
    print("api chat:", out[:400].encode("ascii", errors="replace").decode())
    ok = "qwen" in out.lower() or FAST in out
    if not ok:
        print("WARN: resposta pode ser Groq fallback", file=sys.stderr)
        return 1

    client.close()
    print("OK — host-GPU ativo")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
