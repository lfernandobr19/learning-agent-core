"""Wake-on-LAN magic packet sender."""

from __future__ import annotations

import os
import re
import socket
from typing import Any

_MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$")


def _normalize_mac(mac: str) -> str:
    clean = re.sub(r"[^0-9A-Fa-f]", "", mac or "")
    if len(clean) != 12:
        raise ValueError(f"MAC inválido: {mac!r}")
    return clean.lower()


def send_magic_packet(
    mac: str,
    *,
    broadcast: str | None = None,
    port: int = 9,
) -> dict[str, Any]:
    bcast = (broadcast or os.environ.get("WOL_BROADCAST") or "192.168.18.255").strip()
    mac_hex = _normalize_mac(mac)
    mac_bytes = bytes.fromhex(mac_hex)
    packet = b"\xff" * 6 + mac_bytes * 16
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sent = sock.sendto(packet, (bcast, int(port)))
    finally:
        sock.close()
    return {
        "ok": True,
        "mac": ":".join(mac_hex[i : i + 2] for i in range(0, 12, 2)),
        "broadcast": bcast,
        "port": port,
        "bytes": sent,
    }


def default_windows_mac() -> str:
    return (
        os.environ.get("WINDOWS_WOL_MAC")
        or os.environ.get("PC_DO_LUIS_MAC")
        or "70:85:C2:BE:40:10"
    )


if __name__ == "__main__":
    import sys

    mac = sys.argv[1] if len(sys.argv) > 1 else default_windows_mac()
    print(send_magic_packet(mac))
