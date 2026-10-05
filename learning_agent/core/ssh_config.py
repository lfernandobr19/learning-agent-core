"""Leitura de ~/.ssh/config — mesma fonte que o Cursor usa."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class SshConfigHost:
    name: str
    hostname: str = ""
    user: str = ""
    port: int = 22
    identity_file: str = ""
    source: str = "config"

    def display_label(self) -> str:
        if self.hostname and self.hostname != self.name:
            return f"{self.name} {self.hostname}"
        return self.name

    def connect_target(self) -> str:
        return self.name

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "hostname": self.hostname or self.name,
            "user": self.user,
            "port": self.port,
            "identity_file": self.identity_file,
            "label": self.display_label(),
            "target": self.connect_target(),
            "source": self.source,
        }


def ssh_config_path() -> Path:
    custom = os.environ.get("RAVENNA_SSH_CONFIG", "").strip()
    if custom:
        return Path(custom).expanduser()
    return Path.home() / ".ssh" / "config"


def parse_ssh_config(path: Path | None = None) -> list[SshConfigHost]:
    cfg = path or ssh_config_path()
    if not cfg.is_file():
        return []

    try:
        text = cfg.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    hosts: list[SshConfigHost] = []
    current_names: list[str] = []
    current: dict[str, str] = {}

    def flush() -> None:
        nonlocal current_names, current
        if not current_names:
            return
        hostname = current.get("hostname", "")
        user = current.get("user", "")
        port_raw = current.get("port", "22")
        try:
            port = int(port_raw)
        except ValueError:
            port = 22
        identity = current.get("identityfile", "")
        for name in current_names:
            if "*" in name or "?" in name:
                continue
            hosts.append(
                SshConfigHost(
                    name=name,
                    hostname=hostname or name,
                    user=user,
                    port=port,
                    identity_file=identity,
                )
            )
        current_names = []
        current = {}

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("host "):
            flush()
            current_names = line.split()[1:]
            continue
        if " " not in line:
            continue
        key, _, value = line.partition(" ")
        key = key.lower()
        value = value.strip().strip('"')
        if key in {"hostname", "user", "port", "identityfile"}:
            current[key] = value

    flush()
    return hosts


def find_config_host(name: str, path: Path | None = None) -> SshConfigHost | None:
    needle = name.strip().lower()
    for host in parse_ssh_config(path):
        if host.name.lower() == needle:
            return host
    return None


def parse_ssh_target(raw: str, path: Path | None = None) -> dict[str, Any]:
    """Interpreta alias, user@host, host:port ou `ssh user@host -p 2772`."""
    target = raw.strip()
    if not target:
        raise ValueError("Host SSH obrigatório")

    if target.lower().startswith("ssh "):
        target = target[4:].strip()

    port = 22
    port_flag = re.search(r"(?:\s|^)-p\s+(\d+)\b", target, flags=re.IGNORECASE)
    if port_flag:
        port = int(port_flag.group(1))
        target = (target[: port_flag.start()] + target[port_flag.end() :]).strip()

    cfg_host = find_config_host(target, path)
    if cfg_host:
        return {
            "ssh_config_alias": cfg_host.name,
            "host": cfg_host.hostname,
            "user": cfg_host.user,
            "port": cfg_host.port or port,
            "identity_file": cfg_host.identity_file,
            "label": cfg_host.name,
            "target": cfg_host.name,
        }

    user = ""
    host = target

    if "@" in target:
        user, host = target.rsplit("@", 1)

    host = host.strip()
    if ":" in host and not host.startswith("["):
        host_part, port_part = host.rsplit(":", 1)
        if port_part.isdigit():
            host = host_part
            port = int(port_part)

    host = host.strip()
    if not host:
        raise ValueError("Host SSH inválido")

    return {
        "ssh_config_alias": "",
        "host": host,
        "user": user,
        "port": port,
        "identity_file": "",
        "label": f"{user}@{host}" if user else host,
        "target": f"{user}@{host}:{port}" if user and port != 22 else (f"{user}@{host}" if user else host),
    }
