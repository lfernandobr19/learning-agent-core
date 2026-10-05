"""Best-effort RGB fan signaling for Ravenna process states.

Chat/API run inside ravenna-backend. Prefer host nsenter (real OpenRGB + i2c)
when running in Docker; local openrgb in the container often cannot drive
motherboard RGB even if the binary exists.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "ravenna_rgb_state.sh"
HOST_SCRIPT = "/home/lfernando/learning-agent/scripts/ravenna_rgb_state.sh"
ALPINE_IMAGE = os.environ.get("RAVENNA_RGB_NSENTER_IMAGE", "alpine:3.20")
DIAG = Path(os.environ.get("RAVENNA_RGB_DIAG", str(ROOT / "data" / "diagnostics" / "ravenna-rgb-python.json")))


def _in_docker() -> bool:
    return Path("/.dockerenv").is_file() or os.environ.get("RAVENNA_IN_DOCKER", "").strip() in {
        "1",
        "true",
        "yes",
    }


def _local_openrgb() -> bool:
    return bool(shutil.which("openrgb"))


def _diag(payload: dict) -> None:
    try:
        DIAG.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            **payload,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        DIAG.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _run_host_via_nsenter(state: str, *, wait: bool = False) -> bool:
    """Apply RGB on the bare-metal host from inside Docker."""
    if not shutil.which("docker"):
        _diag({"state": state, "ok": False, "via": "nsenter", "error": "no_docker_bin"})
        return False
    cmd = [
        "docker",
        "run",
        "--rm",
        "--privileged",
        "--pid=host",
        ALPINE_IMAGE,
        "nsenter",
        "-t",
        "1",
        "-m",
        "-u",
        "-i",
        "-n",
        "--",
        "bash",
        HOST_SCRIPT,
        state,
    ]
    try:
        if wait:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=int(os.environ.get("RAVENNA_RGB_TIMEOUT_S", "12")),
                check=False,
            )
            ok = proc.returncode == 0 and "RAVENNA_RGB_OK" in (proc.stdout or "")
            _diag(
                {
                    "state": state,
                    "ok": ok,
                    "via": "nsenter",
                    "rc": proc.returncode,
                    "stdout": (proc.stdout or "")[-400:],
                    "stderr": (proc.stderr or "")[-400:],
                }
            )
            return ok
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        _diag({"state": state, "ok": True, "via": "nsenter_async"})
        return True
    except Exception as exc:
        _diag({"state": state, "ok": False, "via": "nsenter", "error": str(exc)[:300]})
        return False


def _run_local_script(state: str, *, wait: bool = False) -> bool:
    if not SCRIPT.is_file():
        _diag({"state": state, "ok": False, "via": "local", "error": "script_missing"})
        return False
    cmd = ["bash", str(SCRIPT), state]
    try:
        if wait:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=int(os.environ.get("RAVENNA_RGB_TIMEOUT_S", "12")),
                check=False,
            )
            ok = proc.returncode == 0 and "RAVENNA_RGB_OK" in (proc.stdout or "")
            _diag(
                {
                    "state": state,
                    "ok": ok,
                    "via": "local",
                    "rc": proc.returncode,
                    "stdout": (proc.stdout or "")[-400:],
                    "stderr": (proc.stderr or "")[-400:],
                }
            )
            return ok
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        _diag({"state": state, "ok": True, "via": "local_async"})
        return True
    except Exception as exc:
        _diag({"state": state, "ok": False, "via": "local", "error": str(exc)[:300]})
        return False


def set_rgb_state(state: str, *, wait: bool = False) -> None:
    if os.environ.get("RAVENNA_RGB_DISABLE", "").strip() in {"1", "true", "yes"}:
        return
    clean = (state or "").strip().lower()
    if clean not in {"idle", "thinking", "speaking", "trouble"}:
        return
    try:
        # Em Docker o openrgb local costuma falhar no i2c da placa — nsenter no host.
        if _in_docker():
            if _run_host_via_nsenter(clean, wait=wait):
                return
            # fallback se sock/docker falhar mas o script local + openrgb funcionarem
            if _local_openrgb():
                _run_local_script(clean, wait=wait)
            return
        if _local_openrgb() and SCRIPT.is_file():
            _run_local_script(clean, wait=wait)
            return
        _run_host_via_nsenter(clean, wait=wait)
    except Exception as exc:
        _diag({"state": clean, "ok": False, "via": "set_rgb_state", "error": str(exc)[:300]})
