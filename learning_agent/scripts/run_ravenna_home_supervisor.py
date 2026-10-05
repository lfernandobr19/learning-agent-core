#!/usr/bin/env python3
"""Supervisor Ravenna Home — orquestra gemma4-raven na IDE (um épico por run).

Cursor NÃO implementa o projeto: só infra, remediação e este loop.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.strip().startswith("#"):
            continue
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())


_load_dotenv(ROOT / ".env")
_load_dotenv(ROOT / "scripts" / "host-gpu.env")

from ravenna_home_runtime import (  # noqa: E402
    autonomy_payload,
    cooldown,
    cooldown_seconds,
    load_host_env,
    run_timeout,
    safe_mode,
)

load_host_env()

API = os.environ.get("RAVENNA_API_BASE", "http://ravenna-vm:8000").rstrip("/")
IDE = os.environ.get("RAVENNA_IDE_URL", "http://ravenna-vm:5173")
GPU = os.environ.get("RAVENNA_GPU_HOST", "pc-do-luis")
OLLAMA = f"http://{GPU}:11434"
LOG = ROOT / "data" / "diagnostics" / "ravenna-home-supervisor.jsonl"
STATE = ROOT / "data" / "diagnostics" / "ravenna-home-supervisor-state.json"
PROJECT_ID = "ravenna-home"
MAX_EPIC_RETRIES = int(os.environ.get("RAVENNA_HOME_EPIC_RETRIES", "3" if safe_mode() else "5"))
RUN_TIMEOUT = run_timeout()

# Épicos fechados — gemma4-raven implementa cada um na IDE
EPICS: list[dict[str, Any]] = [
    {
        "id": "e1-scaffold",
        "title": "Scaffold + agente autônomo",
        "required_files": [
            "ravenna-home/README.md",
            "ravenna-home/.env.example",
            "agents/projects/ravenna-home/manifest.yaml",
            "agents/curricula/ravenna-home.yaml",
        ],
        "brief": """\
Épico 1 — **Scaffold Ravenna Home** (projeto vazio até aqui).

Você é **gemma4-raven** na IDE Ravenna. Implemente só este épico:

1. `ravenna-home/README.md` — visão, arquitetura dual-motor (**raven** chat + **gemma4-raven** agente), setup.
2. `ravenna-home/.env.example` — HA_URL, HA_TOKEN, TAILSCALE_PC_HOST, RAVENNA_API.
3. `agents/projects/ravenna-home/manifest.yaml` — agente autônomo completo (learning on, mcp_tools, on_failure).
4. `agents/curricula/ravenna-home.yaml` — marcos L2–L5 (HA, PWA, distillation).

**Antes:** `get_project_lessons` project_id=ravenna-home.
**Após falha:** `record_project_lesson`.
Investigue → Diagnóstico → Solução com ```write```. Não peça confirmação.
""",
    },
    {
        "id": "e2-backend",
        "title": "Backend FastAPI",
        "required_files": [
            "ravenna-home/backend/main.py",
            "ravenna-home/backend/homeassistant.py",
            "ravenna-home/backend/pc_status.py",
            "ravenna-home/backend/requirements.txt",
        ],
        "brief": """\
Épico 2 — **Backend FastAPI** em `ravenna-home/backend/`.

- FastAPI com rotas: health, chat proxy para API Ravenna (motor **raven**), HA lights/scenes, PC Ollama status via Tailscale.
- Módulos `homeassistant.py`, `pc_status.py`, `requirements.txt`.
- Sem frontend ainda. Testável com curl.

Use `get_project_lessons` (ravenna-home). Registre lições em falhas.
Investigue → Diagnóstico → Solução. Blocos ```write``` completos.
""",
    },
    {
        "id": "e3-pwa",
        "title": "PWA React/TS",
        "required_files": [
            "ravenna-home/frontend/package.json",
            "ravenna-home/frontend/src/App.tsx",
        ],
        "brief": """\
Épico 3 — **PWA mobile** `ravenna-home/frontend/` (React + TypeScript).

- UI mobile-first, persona Ravenna (PT-BR).
- Chat com backend (motor conversacional **raven**).
- Atalhos: luzes, cenários HA, status PC/GPU.
- PWA manifest + service worker básico.

Consulte lições do projeto. Entregue arquivos completos.
""",
    },
    {
        "id": "e4-mobile-channel",
        "title": "Channel mobile na API",
        "required_files": [
            "ravenna-home/backend/tests/test_health.py",
        ],
        "brief": """\
Épico 4 — **Integração API Ravenna + testes**.

- Adicionar channel `mobile` em `learning_agent/core/chat.py` (greeting + system prompt Ravenna Home) se ainda não existir.
- `ravenna-home/backend/tests/` com pytest (health, HA mock, pc_status mock).
- README atualizado com fluxo Luis → Ravenna VM → PC GPU.

Use lições aprendidas. Valide com ```shell pytest ...``` se possível.
""",
    },
    {
        "id": "e5-mcp-tools",
        "title": "Tools domésticas",
        "required_files": [
            "ravenna-home/tools/home_devices.py",
        ],
        "brief": """\
Épico 5 — **Tools/MCP dispositivos domésticos**.

- `ravenna-home/tools/home_devices.py` — funções seguras (list lights, toggle, scene).
- Documentar no README como expor via MCP.
- Garantir agente `agents/projects/ravenna-home/manifest.yaml` referencia tools.

Feche o MVP Ravenna Home. Consulte `get_project_lessons` antes de cada write.
""",
    },
]

HOTFIX_FILES = (
    "learning_agent/core/workspace_roots.py",
    "learning_agent/core/agent_tools.py",
    "learning_agent/core/agent_project_learning.py",
    "learning_agent/core/agent_autonomy_runner.py",
    "learning_agent/core/web.py",
    "learning_agent/api.py",
    "learning_agent/core/chat.py",
    "learning_agent/config.py",
    "ravenna-ide/frontend/src/components/ChatInputBar.tsx",
)


def _log(event: str, **data: Any) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    row = {"at": datetime.now(timezone.utc).isoformat(), "event": event, **data}
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"[{event}] {json.dumps(data, ensure_ascii=False)[:320]}")


def _save_state(state: dict[str, Any]) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def _load_state() -> dict[str, Any]:
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {}


def sync_workspace(*, full: bool = True) -> bool:
    if not full:
        _log("sync_skip", reason="incremental_disabled")
        return True
    script = ROOT / "learning_agent" / "scripts" / "sync_pc_workspace_to_vm.py"
    _log("sync_start", full=full)
    r = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        timeout=3600,
        cwd=str(ROOT),
        env=os.environ.copy(),
    )
    tail = (r.stdout or r.stderr or "")[-600:]
    _log("sync_done", exit_code=r.returncode, tail=tail)
    return r.returncode == 0


def _api_healthy() -> bool:
    try:
        r = httpx.get(f"{API}/health", timeout=8)
        return r.status_code == 200 and r.json().get("status") == "ok"
    except Exception:
        return False


def fix_vm_workspace_mount(*, restart_docker: bool = False) -> bool:
    """Garante pasta do workspace. Só reinicia container se restart_docker=True e API down."""
    pwd = os.environ.get("RAVENNA_VM_PASSWORD", "")
    if not pwd:
        _log("vm_fix_skip", reason="no RAVENNA_VM_PASSWORD")
        return False
    try:
        import paramiko

        host = os.environ.get("RAVENNA_VM_HOST", "ravenna-vm")
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(host, username="lfernando", password=pwd, timeout=30)
        cmds = ["mkdir -p /home/lfernando/workspace-pc"]
        if restart_docker and not _api_healthy():
            cmds.append("docker restart ravenna-backend 2>/dev/null || true")
        for cmd in cmds:
            stdin, stdout, _ = client.exec_command(f"sudo -S bash -c {repr(cmd)}", timeout=300, get_pty=True)
            stdin.write(pwd + "\n")
            stdin.channel.shutdown_write()
            out = stdout.read().decode("utf-8", errors="replace")
            _log("vm_cmd", cmd=cmd[:80], out=out[-400:].encode("ascii", errors="replace").decode())
        client.close()
        return True
    except Exception as exc:
        _log("vm_fix_error", error=str(exc))
        return False


def deploy_hotfix_files(*, restart_docker: bool = False) -> bool:
    """Copia arquivos na VM (volume learning_agent já montado). Evita docker compose durante runs."""
    pwd = os.environ.get("RAVENNA_VM_PASSWORD", "")
    if not pwd:
        return False
    try:
        import paramiko

        host = os.environ.get("RAVENNA_VM_HOST", "ravenna-vm")
        vm_dir = "/home/lfernando/learning-agent"
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(host, username="lfernando", password=pwd, timeout=30)
        sftp = client.open_sftp()
        for rel in HOTFIX_FILES:
            src = ROOT / rel
            if src.is_file():
                with sftp.file(f"{vm_dir}/{rel}", "w") as fh:
                    fh.write(src.read_text(encoding="utf-8").replace("\r\n", "\n"))
        sftp.close()
        restarted = False
        if restart_docker and not _api_healthy():
            stdin, stdout, _ = client.exec_command(
                "sudo -S docker restart ravenna-backend",
                timeout=120,
                get_pty=True,
            )
            stdin.write(pwd + "\n")
            stdin.channel.shutdown_write()
            stdout.read()
            restarted = True
        client.close()
        _log("deploy_hotfix", files=list(HOTFIX_FILES), restarted=restarted)
        return True
    except Exception as exc:
        _log("deploy_hotfix_error", error=str(exc))
        return False


def warmup_gemma4() -> bool:
    try:
        body = {
            "model": "gemma4-raven",
            "messages": [{"role": "user", "content": "diga ok"}],
            "stream": False,
            "think": False,
            "options": {"num_predict": 8},
        }
        with httpx.Client(timeout=httpx.Timeout(30.0, read=300.0)) as c:
            r = c.post(f"{OLLAMA}/v1/chat/completions", json=body)
        ok = r.status_code == 200
        _log("warmup_gemma4", ok=ok, status=r.status_code)
        return ok
    except Exception as exc:
        _log("warmup_gemma4_error", error=str(exc))
        return False


def wait_api_ready(max_wait: int = 180) -> bool:
    deadline = time.time() + max_wait
    while time.time() < deadline:
        try:
            r = httpx.get(f"{API}/health", timeout=10)
            if r.status_code == 200 and r.json().get("status") == "ok":
                models = (r.json().get("llm_models") or {})
                if models.get("agent") == "gemma4-raven":
                    return True
        except Exception:
            pass
        time.sleep(5)
    return False


def remediate(error_text: str, *, during_run: bool = False) -> None:
    low = error_text.lower()
    if during_run:
        _log("remediate", action="wait_only", during_run=True)
        wait_api_ready(240)
        if not safe_mode():
            warmup_gemma4()
        return
    if "pc-workspace" in low or "workspace não existe" in low:
        sync_workspace(full=False)
        fix_vm_workspace_mount(restart_docker=False)
        wait_api_ready()
    elif "10061" in error_text or "disconnected" in low or "connection refused" in low:
        wait_api_ready(240)
        warmup_gemma4()
    elif "timeout" in low or "timed out" in low:
        warmup_gemma4()
    elif "ollama" in low:
        warmup_gemma4()


def create_conversation(client: httpx.Client) -> str:
    r = client.post(
        f"{API}/api/chat/conversations",
        params={"channel": "ide"},
        json={
            "title": "Ravenna Home — gemma4-raven",
            "project_name": PROJECT_ID,
            "project_root": PROJECT_ID,
        },
    )
    r.raise_for_status()
    return r.json()["conversation"]["id"]


def epic_files_ok(epic: dict[str, Any]) -> tuple[bool, list[str]]:
    required = list(epic.get("required_files") or [])
    missing_local = [rel for rel in required if not (ROOT / rel).is_file()]
    if not missing_local:
        return True, []
    missing_vm = _missing_files_on_vm(missing_local)
    if not missing_vm:
        _pull_files_from_vm(required)
        still = [rel for rel in required if not (ROOT / rel).is_file()]
        return len(still) == 0, still
    return False, missing_vm


def _missing_files_on_vm(relative_paths: list[str]) -> list[str]:
    pwd = os.environ.get("RAVENNA_VM_PASSWORD", "")
    if not pwd or not relative_paths:
        return relative_paths
    try:
        import paramiko

        host = os.environ.get("RAVENNA_VM_HOST", "ravenna-vm")
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(host, username="lfernando", password=pwd, timeout=30)
        missing: list[str] = []
        bases = (
            "/home/lfernando/learning-agent",
            "/home/lfernando/workspace-pc",
        )
        for rel in relative_paths:
            found = False
            for base in bases:
                cmd = f"test -f {base}/{rel} && echo OK"
                stdin, stdout, _ = client.exec_command(cmd, timeout=15)
                stdin.channel.shutdown_write()
                if "OK" in stdout.read().decode("utf-8", errors="replace"):
                    found = True
                    break
            if not found:
                missing.append(rel)
        client.close()
        return missing
    except Exception as exc:
        _log("vm_files_check_error", error=str(exc))
        return relative_paths


def _pull_files_from_vm(relative_paths: list[str]) -> None:
    pwd = os.environ.get("RAVENNA_VM_PASSWORD", "")
    if not pwd:
        return
    try:
        import paramiko

        host = os.environ.get("RAVENNA_VM_HOST", "ravenna-vm")
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(host, username="lfernando", password=pwd, timeout=30)
        sftp = client.open_sftp()
        bases = (
            "/home/lfernando/learning-agent",
            "/home/lfernando/workspace-pc",
        )
        for rel in relative_paths:
            dest = ROOT / rel
            if dest.is_file():
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            for base in bases:
                remote = f"{base}/{rel}"
                try:
                    sftp.get(remote, str(dest))
                    break
                except OSError:
                    continue
        sftp.close()
        client.close()
        _log("pull_from_vm", files=relative_paths)
    except Exception as exc:
        _log("pull_from_vm_error", error=str(exc))


def run_epic(client: httpx.Client, conv_id: str, epic: dict[str, Any], *, retry: int) -> dict[str, Any]:
    lessons_hint = ""
    lessons_path = ROOT / "data" / "project-learning" / f"{PROJECT_ID}.jsonl"
    if lessons_path.is_file():
        lines = lessons_path.read_text(encoding="utf-8").strip().splitlines()
        if lines:
            try:
                last = json.loads(lines[-1])
                lessons_hint = f"\nÚltima lição: {str(last.get('error', ''))[:400]}"
            except json.JSONDecodeError:
                pass

    msg = epic["brief"]
    if retry > 0:
        ok, missing = epic_files_ok(epic)
        msg = (
            f"Retry {retry} — épico `{epic['id']}`. Arquivos em falta: {missing or 'nenhum'}."
            f"{lessons_hint}\n\n"
            f"Use get_project_lessons + record_project_lesson. Corrija e complete.\n\n{epic['brief']}"
        )

    payload = autonomy_payload(
        msg,
        conversation_id=conv_id,
        project_root=PROJECT_ID,
        run_checklist=True,
        supervisor=True,
    )
    t0 = time.time()
    r = client.post(f"{API}/api/agent/autonomy/run", json=payload)
    elapsed = round(time.time() - t0, 1)
    try:
        data = r.json()
    except Exception:
        data = {"detail": r.text[:2000]}
    data["_elapsed_s"] = elapsed
    data["_status_code"] = r.status_code
    data["_epic_id"] = epic["id"]
    return data


def main() -> int:
    reset = "--reset" in sys.argv
    state = {} if reset else _load_state()
    if state.get("status") == "blocked":
        state["status"] = "resuming"
        state.pop("blocked_epic", None)
        _save_state(state)
    conv_id = state.get("conversation_id", "")
    epic_index = int(state.get("epic_index", 0))

    print(f"Supervisor Ravenna Home [{'SAFE' if safe_mode() else 'normal'}] cooldown={cooldown_seconds()}s", flush=True)
    _log("supervisor_start", api=API, ide=IDE, epic_index=epic_index, reset=reset, safe_mode=safe_mode())

    docker_on_boot = not safe_mode()
    if epic_index == 0 and not state.get("bootstrapped"):
        sync_workspace(full=True)
        deploy_hotfix_files(restart_docker=docker_on_boot)
        fix_vm_workspace_mount(restart_docker=docker_on_boot)
        wait_api_ready(240)
        if not safe_mode():
            warmup_gemma4()
        state["bootstrapped"] = True
        _save_state(state)

    if not wait_api_ready(60):
        _log("api_not_ready")
        fix_vm_workspace_mount(restart_docker=docker_on_boot)
        deploy_hotfix_files(restart_docker=docker_on_boot)
        if not wait_api_ready(180):
            return 1

    client = httpx.Client(timeout=httpx.Timeout(60.0, read=RUN_TIMEOUT))

    try:
        if not conv_id or reset:
            conv_id = create_conversation(client)
            state = {"conversation_id": conv_id, "epic_index": 0, "bootstrapped": True}
            _save_state(state)
            _log("conversation_created", conversation_id=conv_id, ide=IDE)

        while epic_index < len(EPICS):
            epic = EPICS[epic_index]
            files_ok, missing = epic_files_ok(epic)
            if files_ok:
                _log("epic_skip_done", epic=epic["id"])
                epic_index += 1
                state["epic_index"] = epic_index
                _save_state(state)
                continue

            passed_epic = False
            for retry in range(MAX_EPIC_RETRIES):
                state["status"] = "running"
                state["current_epic"] = epic["id"]
                state["retry"] = retry
                _save_state(state)

                _log("epic_run_start", epic=epic["id"], retry=retry, conversation_id=conv_id)
                try:
                    result = run_epic(client, conv_id, epic, retry=retry)
                except Exception as exc:
                    result = {"detail": str(exc), "_status_code": 0}
                    _log("epic_run_exception", error=str(exc), tb=traceback.format_exc()[-800:])

                err = json.dumps(result, ensure_ascii=False)
                autonomy = result.get("autonomy") or {}
                passed = bool(autonomy.get("passed"))
                files_ok, missing = epic_files_ok(epic)

                _log(
                    "epic_run_end",
                    epic=epic["id"],
                    retry=retry,
                    status_code=result.get("_status_code", 0),
                    autonomy_passed=passed,
                    files_ok=files_ok,
                    missing=missing,
                    lesson_recorded=autonomy.get("lessonRecorded"),
                    elapsed=result.get("_elapsed_s"),
                )

                if passed and files_ok:
                    passed_epic = True
                    sync_workspace(full=False)
                    break
                if files_ok and not passed:
                    _log("epic_files_without_autonomy", epic=epic["id"], retry=retry)
                    passed_epic = True
                    sync_workspace(full=False)
                    break

                remediate(err, during_run=True)
                cooldown(label=f"{epic['id']}-retry{retry}")

            if not passed_epic:
                state["status"] = "blocked"
                state["blocked_epic"] = epic["id"]
                _save_state(state)
                _log("epic_blocked", epic=epic["id"], missing=missing)
                print(f"\nBLOQUEADO no épico {epic['id']} — IDE: {IDE} | conversa: {conv_id}")
                return 2

            epic_index += 1
            state["epic_index"] = epic_index
            state["status"] = "running"
            _save_state(state)
            cooldown(label=epic["id"])

        state["status"] = "completed"
        state["passed"] = True
        _save_state(state)
        _log("supervisor_success", conversation_id=conv_id, epics=len(EPICS))
        print(f"\nDONE — todos os épicos. IDE: {IDE} | conversa: {conv_id}")
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
