"""Sessão de debug Python (debugpy) — DAP-1 mínimo."""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from learning_agent.core.workspace_roots import get_root_path

_sessions: dict[str, "DebugSession"] = {}


@dataclass
class DebugSession:
    id: str
    root_id: str
    script: str
    port: int
    process: subprocess.Popen[str] | None = None
    breakpoints: dict[str, list[int]] = field(default_factory=dict)
    status: str = "stopped"
    logs: list[str] = field(default_factory=list)

    def append_log(self, line: str) -> None:
        self.logs.append(line)
        if len(self.logs) > 200:
            self.logs = self.logs[-200:]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "root_id": self.root_id,
            "script": self.script,
            "port": self.port,
            "status": self.status,
            "breakpoints": self.breakpoints,
            "logs": self.logs[-40:],
        }


def _resolve_script(root_id: str, script: str) -> Path:
    root = get_root_path(root_id)
    rel = script.strip().replace("\\", "/").lstrip("/")
    inner = rel.split("/", 1)[1] if rel.startswith(f"{root_id}/") else rel
    candidate = (root / inner).resolve()
    if not candidate.is_file():
        raise FileNotFoundError(f"Script não encontrado: {script}")
    if root not in candidate.parents and candidate != root:
        raise PermissionError("Script fora do workspace")
    return candidate


def create_session(root_id: str, script: str, *, port: int = 5678) -> DebugSession:
    session_id = uuid.uuid4().hex[:12]
    session = DebugSession(id=session_id, root_id=root_id, script=script, port=port)
    _sessions[session_id] = session
    return session


def get_session(session_id: str) -> DebugSession | None:
    return _sessions.get(session_id)


def set_breakpoints(session_id: str, path: str, lines: list[int]) -> DebugSession:
    session = _sessions.get(session_id)
    if not session:
        raise KeyError("sessão não encontrada")
    clean = sorted({int(line) for line in lines if int(line) > 0})
    session.breakpoints[path.replace("\\", "/")] = clean
    return session


def start_session(session_id: str) -> DebugSession:
    session = _sessions.get(session_id)
    if not session:
        raise KeyError("sessão não encontrada")
    if session.process and session.process.poll() is None:
        session.status = "running"
        return session

    script_path = _resolve_script(session.root_id, session.script)
    root = get_root_path(session.root_id)
    python = shutil.which("python3") or shutil.which("python") or sys.executable

    env = {**os.environ, "PYTHONPATH": str(root)}
    cmd = [
        python,
        "-m",
        "debugpy",
        "--listen",
        str(session.port),
        "--wait-for-client",
        str(script_path),
    ]
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(root),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        session.status = "error"
        session.append_log(f"Falha ao iniciar debugpy: {exc}")
        return session

    session.process = proc
    session.status = "running"
    session.append_log(f"debugpy listen :{session.port} → {script_path.name}")
    return session


def stop_session(session_id: str) -> DebugSession:
    session = _sessions.get(session_id)
    if not session:
        raise KeyError("sessão não encontrada")
    if session.process and session.process.poll() is None:
        session.process.terminate()
        try:
            session.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            session.process.kill()
    session.process = None
    session.status = "stopped"
    session.append_log("Sessão encerrada")
    return session


async def poll_session_output(session_id: str) -> None:
    session = _sessions.get(session_id)
    if not session or not session.process or not session.process.stdout:
        return
    while session.process.poll() is None:
        line = await asyncio.to_thread(session.process.stdout.readline)
        if not line:
            break
        session.append_log(line.rstrip())
    if session.process and session.process.poll() is not None:
        session.status = "stopped"
        session.append_log(f"Processo exit {session.process.returncode}")


def read_launch_configs(root_id: str) -> list[dict[str, Any]]:
    import json

    root = get_root_path(root_id)
    launch_path = root / ".vscode" / "launch.json"
    if not launch_path.is_file():
        return []
    try:
        data = json.loads(launch_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    configs = data.get("configurations") if isinstance(data, dict) else []
    if not isinstance(configs, list):
        return []
    out: list[dict[str, Any]] = []
    for cfg in configs:
        if isinstance(cfg, dict) and cfg.get("type") == "python":
            out.append(cfg)
    return out


def handle_dap_message(session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    command = str(payload.get("command") or "")
    if command == "initialize":
        return {
            "type": "response",
            "command": "initialize",
            "success": True,
            "body": {"supportsConfigurationDoneRequest": True},
        }
    if command == "launch":
        session = start_session(session_id)
        return {"type": "response", "command": "launch", "success": True, "body": session.to_dict()}
    if command == "disconnect":
        session = stop_session(session_id)
        return {"type": "response", "command": "disconnect", "success": True, "body": session.to_dict()}
    if command == "setBreakpoints":
        args = payload.get("arguments") or {}
        path = str(args.get("source", {}).get("path") or "")
        bps = [int(b.get("line") or 0) for b in (args.get("breakpoints") or [])]
        set_breakpoints(session_id, path, bps)
        return {
            "type": "response",
            "command": "setBreakpoints",
            "success": True,
            "body": {"breakpoints": [{"verified": True, "line": line} for line in bps if line > 0]},
        }
    return {"type": "response", "command": command, "success": False, "message": "unsupported"}
