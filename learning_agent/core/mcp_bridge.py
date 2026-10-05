"""Bridge REST para o servidor MCP embutido (Fase 5 IDE)."""

from __future__ import annotations

import asyncio
import json
import socket
from typing import Any

from learning_agent.config import MCP_HTTP_PORT

# Tools bloqueadas na UI — use endpoints REST dedicados ou Cursor MCP.
IDE_BLOCKED_TOOLS = frozenset(
    {
        "start_teaching_theater",
        "stop_teaching_theater",
        "sync_to_cloud",
        "sync_from_cloud",
        "run_active_learning",
        "create_student_model",
    }
)


class McpBridgeError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _http_server_reachable(host: str = "127.0.0.1", port: int = MCP_HTTP_PORT) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.35):
            return True
    except OSError:
        return False


def _run_async(coro):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    # Dentro de request async FastAPI — criar task nova não é ideal; usar thread pool
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def get_status() -> dict[str, Any]:
    from learning_agent.mcp_server import mcp

    tools = _run_async(mcp.list_tools())
    http_up = _http_server_reachable()
    return {
        "server": mcp.name,
        "embedded": True,
        "tool_count": len(tools),
        "http_port": MCP_HTTP_PORT,
        "http_running": http_up,
        "transport_hint": "stdio (Cursor) ou streamable-http na porta configurada",
        "blocked_from_ide": sorted(IDE_BLOCKED_TOOLS),
    }


def list_tools() -> list[dict[str, Any]]:
    from learning_agent.mcp_server import mcp

    raw = _run_async(mcp.list_tools())
    out: list[dict[str, Any]] = []
    for tool in raw:
        name = tool.name
        out.append(
            {
                "name": name,
                "description": tool.description or "",
                "input_schema": tool.inputSchema or {},
                "ide_invokable": name not in IDE_BLOCKED_TOOLS,
            }
        )
    out.sort(key=lambda t: t["name"])
    return out


def _extract_result_text(blocks: Any) -> str:
    if not blocks:
        return ""
    parts: list[str] = []
    for block in blocks:
        text = getattr(block, "text", None)
        if text is not None:
            parts.append(text)
        elif isinstance(block, dict) and block.get("text"):
            parts.append(str(block["text"]))
    return "\n".join(parts)


def invoke_tool(name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from learning_agent.mcp_server import mcp

    clean_name = (name or "").strip()
    if not clean_name:
        raise McpBridgeError("Nome da tool é obrigatório.", 400)
    if clean_name in IDE_BLOCKED_TOOLS:
        raise McpBridgeError(
            f"Tool '{clean_name}' não disponível pela IDE — use REST ou Cursor MCP.",
            403,
        )

    tools = _run_async(mcp.list_tools())
    known = {t.name for t in tools}
    if clean_name not in known:
        raise McpBridgeError(f"Tool desconhecida: {clean_name}", 404)

    args = arguments if isinstance(arguments, dict) else {}
    try:
        content_blocks, structured = _run_async(mcp.call_tool(clean_name, args))
    except Exception as exc:
        raise McpBridgeError(str(exc), 500) from exc

    text = _extract_result_text(content_blocks)
    parsed: Any = None
    if text:
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None

    return {
        "tool": clean_name,
        "ok": True,
        "text": text,
        "data": parsed,
        "structured": structured,
    }
