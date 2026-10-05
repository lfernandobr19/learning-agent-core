"""Terminal Ravenna IDE — PTY (preferido) com fallback pipe."""

from __future__ import annotations

import asyncio
import os
import sys
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from learning_agent.config import PROJECT_ROOT

DEFAULT_COLS = 120
DEFAULT_ROWS = 32


class TerminalBackend(ABC):
    mode: str

    @abstractmethod
    async def start(self, cwd: Path, cols: int, rows: int) -> str:
        """Inicia shell; retorna banner."""

    @abstractmethod
    async def write(self, data: str) -> None:
        pass

    @abstractmethod
    async def read_chunk(self) -> bytes:
        pass

    @abstractmethod
    async def resize(self, cols: int, rows: int) -> None:
        pass

    @abstractmethod
    async def close(self) -> None:
        pass


def _remote_shell_argv() -> list[str] | None:
    term = os.environ.get("REMOTE_SSH_TERMINAL", os.environ.get("remoteapp_SSH_TERMINAL", "true")).strip().lower()
    if term in {"0", "false", "no", "off"}:
        return None
    try:
        from learning_agent.core.remote_workspace import remote_terminal_argv

        return remote_terminal_argv()
    except Exception:
        return None


class PipeBackend(TerminalBackend):
    mode = "pipe"

    def __init__(self) -> None:
        self._proc: asyncio.subprocess.Process | None = None

    async def start(self, cwd: Path, cols: int, rows: int) -> str:
        del cols, rows
        remote_argv = _remote_shell_argv()
        if remote_argv:
            self._proc = await asyncio.create_subprocess_exec(
                *remote_argv,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            shell = f"SSH ({remote_argv[0]})"
            return (
                f"Ravenna Terminal — {shell} · servidor remoto\r\n"
                f"\x1b[33m[dica: terminal conectado via SSH]\x1b[0m\r\n"
            )
        if sys.platform == "win32":
            self._proc = await asyncio.create_subprocess_exec(
                "powershell.exe",
                "-NoLogo",
                "-NoProfile",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(cwd),
            )
            shell = "PowerShell (pipe)"
        else:
            self._proc = await asyncio.create_subprocess_exec(
                "/bin/bash",
                "--login",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(cwd),
            )
            shell = "bash (pipe)"
        return f"Ravenna Terminal — {shell} · {cwd.name}\r\n\x1b[33m[dica: PTY indisponível — alguns comandos interativos podem falhar]\x1b[0m\r\n"

    async def write(self, data: str) -> None:
        if self._proc and self._proc.stdin:
            self._proc.stdin.write(data.encode("utf-8"))
            await self._proc.stdin.drain()

    async def read_chunk(self) -> bytes:
        if not self._proc or not self._proc.stdout:
            return b""
        return await self._proc.stdout.read(4096)

    async def resize(self, cols: int, rows: int) -> None:
        del cols, rows

    async def close(self) -> None:
        if self._proc and self._proc.returncode is None:
            self._proc.kill()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                pass
        self._proc = None


class PtyBackend(TerminalBackend):
    mode = "pty"

    def __init__(self) -> None:
        self._pty: Any = None

    async def start(self, cwd: Path, cols: int, rows: int) -> str:
        if sys.platform == "win32":
            from winpty import PtyProcess  # pywinpty 3.x

            self._pty = PtyProcess.spawn(
                "powershell.exe",
                cwd=str(cwd),
                dimensions=(cols, rows),
            )
            shell = "PowerShell (PTY)"
        else:
            import pty
            import subprocess

            import os

            master, slave = pty.openpty()
            proc = subprocess.Popen(
                ["/bin/bash", "--login"],
                stdin=slave,
                stdout=slave,
                stderr=slave,
                cwd=str(cwd),
                close_fds=True,
            )
            os.close(slave)
            self._pty = {"master": master, "proc": proc}
            shell = "bash (PTY)"
        return f"Ravenna Terminal — {shell} · {cwd.name}\r\n"

    def _read_sync(self) -> bytes:
        if sys.platform == "win32":
            if not self._pty or not self._pty.isalive():
                return b""
            try:
                return self._pty.read(4096)
            except EOFError:
                return b""
        master = self._pty["master"]
        import os

        try:
            return os.read(master, 4096)
        except OSError:
            return b""

    def _write_sync(self, data: str) -> None:
        if sys.platform == "win32":
            if self._pty and self._pty.isalive():
                self._pty.write(data)
        else:
            import os

            os.write(self._pty["master"], data.encode("utf-8"))

    async def write(self, data: str) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._write_sync, data)

    async def read_chunk(self) -> bytes:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._read_sync)

    async def resize(self, cols: int, rows: int) -> None:
        if sys.platform == "win32" and self._pty:
            try:
                self._pty.set_size(cols, rows)
            except Exception:
                pass

    async def close(self) -> None:
        if sys.platform == "win32":
            if self._pty:
                try:
                    if self._pty.isalive():
                        self._pty.close(True)
                except Exception:
                    pass
        elif self._pty:
            proc = self._pty.get("proc")
            if proc and proc.poll() is None:
                proc.kill()
            import os

            try:
                os.close(self._pty["master"])
            except OSError:
                pass
        self._pty = None


def create_backend() -> TerminalBackend:
    if _remote_shell_argv():
        return PipeBackend()
    if sys.platform == "win32":
        try:
            from winpty import PtyProcess  # noqa: F401

            return PtyBackend()
        except ImportError:
            return PipeBackend()
    try:
        import pty  # noqa: F401

        return PtyBackend()
    except ImportError:
        return PipeBackend()


class TerminalSession:
    def __init__(self, cwd: Path | None = None) -> None:
        self.cwd = cwd or PROJECT_ROOT
        self.backend = create_backend()
        self._cols = DEFAULT_COLS
        self._rows = DEFAULT_ROWS

    async def start(self) -> str:
        return await self.backend.start(self.cwd, self._cols, self._rows)

    @property
    def mode(self) -> str:
        return self.backend.mode

    async def write(self, data: str) -> None:
        await self.backend.write(data)

    async def resize(self, cols: int, rows: int) -> None:
        self._cols = max(cols, 20)
        self._rows = max(rows, 5)
        await self.backend.resize(self._cols, self._rows)

    async def pump_output(self, websocket: WebSocket) -> None:
        while True:
            chunk = await self.backend.read_chunk()
            if not chunk:
                break
            text = chunk.decode("utf-8", errors="replace")
            await websocket.send_json({"type": "output", "data": text})

    async def close(self) -> None:
        await self.backend.close()


async def handle_terminal_connection(websocket: WebSocket) -> None:
    await websocket.accept()
    session = TerminalSession()
    pump_task: asyncio.Task[None] | None = None

    try:
        banner = await session.start()
        await websocket.send_json(
            {
                "type": "ready",
                "backend": session.mode,
                "cwd": str(session.cwd),
            }
        )
        await websocket.send_json({"type": "output", "data": banner})

        pump_task = asyncio.create_task(session.pump_output(websocket))

        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")
            if msg_type == "input":
                await session.write(data.get("data", ""))
            elif msg_type == "resize":
                cols = int(data.get("cols", DEFAULT_COLS))
                rows = int(data.get("rows", DEFAULT_ROWS))
                await session.resize(cols, rows)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        try:
            await websocket.send_json(
                {"type": "output", "data": f"\r\n[terminal erro: {exc}]\r\n"}
            )
        except Exception:
            pass
    finally:
        if pump_task and not pump_task.done():
            pump_task.cancel()
            try:
                await pump_task
            except asyncio.CancelledError:
                pass
        await session.close()
