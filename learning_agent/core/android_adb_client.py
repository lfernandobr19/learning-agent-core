"""ADB control via Ravenna Android Agent (Termux local adb + wireless debugging)."""
from __future__ import annotations

from typing import Any

from learning_agent.core import android_agent_client as android


def status() -> dict[str, Any]:
    return android._post("/adb/status", {}, timeout=30.0)  # noqa: SLF001


def pair(*, port: int, code: str, host: str = "127.0.0.1") -> dict[str, Any]:
    return android._post(  # noqa: SLF001
        "/adb/pair",
        {"host": host, "port": int(port), "code": str(code)},
        timeout=60.0,
    )


def connect(*, port: int | None = None, host: str = "127.0.0.1") -> dict[str, Any]:
    payload: dict[str, Any] = {"host": host}
    if port is not None:
        payload["port"] = int(port)
    return android._post("/adb/connect", payload, timeout=45.0)  # noqa: SLF001


def install(path: str) -> dict[str, Any]:
    return android._post("/adb/install", {"path": path}, timeout=200.0)  # noqa: SLF001


def shell(command: str, *, timeout: int = 45) -> dict[str, Any]:
    return android._post(  # noqa: SLF001
        "/adb/shell",
        {"command": command, "timeout": int(timeout)},
        timeout=float(timeout + 15),
    )
