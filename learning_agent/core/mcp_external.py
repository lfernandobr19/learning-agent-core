"""MCP externo — lê mcp.json do workspace e do usuário (paridade Cursor/VS Code)."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from learning_agent.config import PROJECT_ROOT

MCP_FILENAMES = ("mcp.json", ".cursor/mcp.json")
WORKSPACE_MCP_PATH = PROJECT_ROOT / ".cursor" / "mcp.json"


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


def discover_config_paths() -> list[Path]:
    roots = [PROJECT_ROOT, Path.home() / ".cursor", Path.home()]
    found: list[Path] = []
    for root in roots:
        for name in MCP_FILENAMES:
            p = root / name if "/" not in name else root / name.replace("/", os.sep)
            if p.is_file():
                found.append(p)
    return found


def parse_servers(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Suporta formato Cursor { mcpServers: { name: { command, args } } }."""
    servers: list[dict[str, Any]] = []
    block = config.get("mcpServers") or config.get("servers") or {}
    if isinstance(block, dict):
        for name, spec in block.items():
            if not isinstance(spec, dict):
                continue
            servers.append(
                {
                    "name": name,
                    "command": spec.get("command") or spec.get("cmd"),
                    "args": spec.get("args") or [],
                    "env": spec.get("env") or {},
                    "transport": spec.get("transport") or "stdio",
                }
            )
    return servers


def load_external_mcp() -> dict[str, Any]:
    configs: list[dict[str, Any]] = []
    all_servers: list[dict[str, Any]] = []
    for path in discover_config_paths():
        raw = _read_json(path)
        if not raw:
            continue
        servers = parse_servers(raw)
        configs.append({"path": str(path), "server_count": len(servers)})
        for s in servers:
            s["source"] = str(path)
            all_servers.append(s)
    return {
        "success": True,
        "config_files": configs,
        "servers": all_servers,
        "server_count": len(all_servers),
    }


def _load_workspace_config() -> dict[str, Any]:
    raw = _read_json(WORKSPACE_MCP_PATH) or {}
    if not isinstance(raw.get("mcpServers"), dict):
        raw["mcpServers"] = {}
    return raw


def save_workspace_server(
    name: str,
    *,
    command: str,
    args: list[str] | None = None,
    env: dict[str, str] | None = None,
    transport: str = "stdio",
) -> dict[str, Any]:
    server_name = name.strip()
    if not server_name:
        raise ValueError("Nome do servidor obrigatório")
    if not command.strip():
        raise ValueError("Comando do servidor obrigatório")

    config = _load_workspace_config()
    config["mcpServers"][server_name] = {
        "command": command.strip(),
        "args": args or [],
        "env": env or {},
        "transport": transport or "stdio",
    }
    WORKSPACE_MCP_PATH.parent.mkdir(parents=True, exist_ok=True)
    WORKSPACE_MCP_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "success": True,
        "path": str(WORKSPACE_MCP_PATH),
        "server": {"name": server_name, **config["mcpServers"][server_name]},
    }


def remove_workspace_server(name: str) -> dict[str, Any]:
    server_name = name.strip()
    if not server_name:
        raise ValueError("Nome do servidor obrigatório")
    config = _load_workspace_config()
    existed = server_name in config["mcpServers"]
    config["mcpServers"].pop(server_name, None)
    WORKSPACE_MCP_PATH.parent.mkdir(parents=True, exist_ok=True)
    WORKSPACE_MCP_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"success": True, "removed": existed, "name": server_name, "path": str(WORKSPACE_MCP_PATH)}


def spawn_server(name: str, *, dry_run: bool = True) -> dict[str, Any]:
    """Dry-run por padrão — spawn real exige aprovação explícita."""
    data = load_external_mcp()
    match = next((s for s in data.get("servers") or [] if s.get("name") == name), None)
    if not match:
        return {"success": False, "error": f"servidor MCP não encontrado: {name}"}
    if dry_run:
        return {
            "success": True,
            "dry_run": True,
            "server": match,
            "detail": "Spawn simulado — configure transport stdio no Cursor ou habilite live spawn",
        }
    return {"success": False, "error": "live spawn desabilitado na IDE (segurança)"}


# ---------------------------------------------------------------------------
# Cliente stdio MCP (JSON-RPC) — invocação real de tools externas
# ---------------------------------------------------------------------------

import queue
import subprocess
import threading


def _start_mcp_reader(proc: subprocess.Popen) -> queue.Queue[dict[str, Any]]:
    """Leitor único de stdout do processo MCP — empurra mensagens parseadas."""
    q: queue.Queue[dict[str, Any]] = queue.Queue()
    stdout = proc.stdout
    if stdout is None:
        return q

    def _reader() -> None:
        try:
            for line in iter(stdout.readline, ""):
                if not line:
                    break
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(msg, dict):
                    q.put(msg)
        except Exception:
            pass

    threading.Thread(target=_reader, daemon=True).start()
    return q


def _rpc_request(proc: subprocess.Popen, mq: queue.Queue[dict[str, Any]], rid: int, method: str, params: dict[str, Any], timeout: float) -> dict[str, Any] | None:
    """Envia request JSON-RPC e aguarda resposta com o id correspondente."""
    payload = json.dumps(
        {"jsonrpc": "2.0", "id": rid, "method": method, "params": params},
        ensure_ascii=False,
    ) + "\n"
    stdin = proc.stdin
    if stdin is None:
        return {"error": "stdin não disponível"}
    try:
        stdin.write(payload)
        stdin.flush()
    except (OSError, ValueError) as exc:
        return {"error": f"write falhou: {exc}"}

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            msg = mq.get(timeout=0.5)
        except queue.Empty:
            continue
        if msg.get("id") == rid:
            return msg
    return None


def _rpc_notify(proc: subprocess.Popen, method: str, params: dict[str, Any]) -> None:
    payload = json.dumps({"jsonrpc": "2.0", "method": method, "params": params}, ensure_ascii=False) + "\n"
    stdin = proc.stdin
    if stdin is None:
        return
    try:
        stdin.write(payload)
        stdin.flush()
    except (OSError, ValueError):
        pass


def call_mcp_tool(server_name: str, tool_name: str, arguments: dict[str, Any] | None = None, *, timeout: float = 30.0) -> dict[str, Any]:
    """Invoca uma tool de um servidor MCP externo (stdio) via JSON-RPC."""
    if not server_name.strip():
        return {"success": False, "error": "server obrigatório"}
    if not tool_name.strip():
        return {"success": False, "error": "tool obrigatória"}

    data = load_external_mcp()
    server = next((s for s in data.get("servers") or [] if s.get("name") == server_name.strip()), None)
    if not server:
        return {"success": False, "error": f"servidor MCP não encontrado: {server_name}"}
    command = server.get("command")
    if not command:
        return {"success": False, "error": "servidor sem command"}
    if server.get("transport", "stdio") != "stdio":
        return {"success": False, "error": f"transport {server.get('transport')} não suportado (só stdio)"}

    argv = [command, *(server.get("args") or [])]
    env = {**os.environ, **{str(k): str(v) for k, v in (server.get("env") or {}).items()}}
    try:
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
    except Exception as exc:
        return {"success": False, "error": f"falha ao iniciar servidor: {exc}"}

    try:
        mq = _start_mcp_reader(proc)
        init = _rpc_request(
            proc, mq, 1, "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "ravenna-ide", "version": "1.0.0"},
            },
            timeout,
        )
        if init is None:
            return {"success": False, "error": "sem resposta initialize (timeout/EOF)"}
        if init.get("error"):
            return {"success": False, "error": f"initialize error: {init['error']}"}

        _rpc_notify(proc, "notifications/initialized", {})

        result = _rpc_request(proc, mq, 2, "tools/call", {"name": tool_name.strip(), "arguments": arguments or {}}, timeout)
        if result is None:
            return {"success": False, "error": "sem resposta tools/call (timeout/EOF)"}
        if result.get("error"):
            return {"success": False, "error": f"tools/call error: {result['error']}"}

        content = (result.get("result") or {}).get("content") or []
        text_parts = [
            str(c.get("text") or "")
            for c in content
            if isinstance(c, dict) and c.get("type") == "text"
        ]
        return {
            "success": True,
            "server": server_name.strip(),
            "tool": tool_name.strip(),
            "content": content,
            "text": "\n".join(text_parts),
        }
    finally:
        try:
            proc.terminate()
        except Exception:
            pass
        try:
            proc.wait(timeout=3)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
