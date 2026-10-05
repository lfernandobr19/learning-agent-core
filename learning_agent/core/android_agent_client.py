"""HTTP client for Ravenna Android Agent (m55 via Termux + Tailscale)."""
from __future__ import annotations

import os
from typing import Any, Iterator

import httpx

DEFAULT_URL = "http://100.85.65.115:8781"
DEFAULT_TOKEN = "ravenna-android-agent-2026"


def _base_url() -> str:
    return (os.environ.get("ANDROID_AGENT_URL") or DEFAULT_URL).rstrip("/")


def _token() -> str:
    return (
        os.environ.get("ANDROID_AGENT_TOKEN")
        or os.environ.get("RAVENNA_ANDROID_AGENT_TOKEN")
        or DEFAULT_TOKEN
    )


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_token()}"}


def _post(path: str, payload: dict[str, Any], *, timeout: float = 90.0) -> dict[str, Any]:
    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.post(f"{_base_url()}{path}", json=payload, headers=_headers())
        if r.status_code >= 400:
            return {"ok": False, "error": r.text[:500], "status_code": r.status_code, "target": "android"}
        data = r.json()
        if isinstance(data, dict):
            data.setdefault("ok", True)
            data["target"] = "android"
        return data
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "target": "android"}


def _get(path: str, *, params: dict[str, Any] | None = None, timeout: float = 30.0) -> dict[str, Any]:
    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.get(f"{_base_url()}{path}", params=params or {}, headers=_headers())
        if r.status_code >= 400:
            return {"ok": False, "error": r.text[:500], "status_code": r.status_code, "target": "android"}
        data = r.json()
        if isinstance(data, dict):
            data.setdefault("ok", True)
            data["target"] = "android"
        return data
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "target": "android"}


def health() -> dict[str, Any]:
    try:
        with httpx.Client(timeout=10.0) as client:
            r = client.get(f"{_base_url()}/health")
        data = r.json() if r.status_code < 400 else {"ok": False}
        if isinstance(data, dict):
            data["target"] = "android"
        return data
    except Exception as exc:
        return {"ok": False, "error": str(exc), "target": "android"}


def status() -> dict[str, Any]:
    return _get("/status", timeout=20.0)


def exec_command(command: str, *, timeout: int = 120) -> dict[str, Any]:
    return _post("/exec", {"command": command, "timeout": timeout}, timeout=float(timeout + 10))


def open_app(name: str) -> dict[str, Any]:
    return _post("/open-app", {"name": name})


def close_app(name: str) -> dict[str, Any]:
    return _post("/close-app", {"name": name})


def open_url(url: str) -> dict[str, Any]:
    return _post("/open-url", {"url": url})


def list_dir(path: str) -> dict[str, Any]:
    data = _post("/list-dir", {"path": path}, timeout=60.0)
    data["ok"] = bool(data.get("ok") or data.get("exit_code") == 0)
    return data


def find_files(query: str, *, kind: str = "any", max_results: int = 20) -> dict[str, Any]:
    data = _post(
        "/find-files",
        {"query": query, "kind": kind, "max_results": max_results},
        timeout=120.0,
    )
    if not isinstance(data, dict):
        return {"ok": False, "error": "resposta invalida", "matches": [], "target": "android"}
    data.setdefault("matches", [])
    data["target"] = "android"
    return data


def read_file(path: str, *, max_bytes: int = 512_000) -> dict[str, Any]:
    return _post("/read-file", {"path": path, "max_bytes": max_bytes}, timeout=90.0)


def battery() -> dict[str, Any]:
    return _get("/battery", timeout=20.0)


def notify(content: str, *, title: str = "Ravenna", id: str = "ravenna") -> dict[str, Any]:
    return _post("/notify", {"title": title, "content": content, "id": id})


def toast(text: str) -> dict[str, Any]:
    return _post("/toast", {"text": text})


def clipboard_get() -> dict[str, Any]:
    return _get("/clipboard", timeout=15.0)


def clipboard_set(text: str) -> dict[str, Any]:
    return _post("/clipboard", {"text": text})


def location() -> dict[str, Any]:
    return _get("/location", timeout=50.0)


def packages(query: str = "") -> dict[str, Any]:
    return _get("/packages", params={"q": query}, timeout=30.0)


def download_url(url: str, *, dest: str = "", timeout: int = 300) -> dict[str, Any]:
    payload: dict[str, Any] = {"url": url, "timeout": timeout}
    if dest:
        payload["dest"] = dest
    return _post("/download", payload, timeout=float(timeout + 30))


def write_file(path: str, content: str, *, encoding: str = "utf8") -> dict[str, Any]:
    return _post(
        "/write-file",
        {"path": path, "content": content, "encoding": encoding},
        timeout=120.0,
    )


def open_file(path: str) -> dict[str, Any]:
    return _post("/open-file", {"path": path}, timeout=45.0)


def pull_file_to_media(android_path: str) -> dict[str, Any]:
    from learning_agent.core.chat_media import save_media_stream

    path = (android_path or "").strip()
    if not path:
        return {"ok": False, "error": "path obrigatorio", "target": "android"}
    fname = path.replace("\\", "/").split("/")[-1] or "arquivo.bin"
    try:
        timeout = httpx.Timeout(30.0, read=None)
        with httpx.stream(
            "GET",
            f"{_base_url()}/file",
            params={"path": path},
            headers=_headers(),
            timeout=timeout,
        ) as r:
            if r.status_code >= 400:
                return {
                    "ok": False,
                    "error": r.text[:500],
                    "status_code": r.status_code,
                    "target": "android",
                }

            def _iter() -> Iterator[bytes]:
                for chunk in r.iter_bytes(1024 * 1024):
                    yield chunk

            record = save_media_stream(_iter(), fname, source="android")
            return {
                "ok": True,
                "media_id": record.get("id"),
                "media_url": record.get("url"),
                "media_type": record.get("type"),
                "filename": record.get("filename"),
                "mime": record.get("mime"),
                "size": record.get("size"),
                "source": record.get("source"),
                "android_path": path,
                "target": "android",
            }
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "target": "android"}
