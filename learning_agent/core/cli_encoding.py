"""Stdout UTF-8 no Windows (evita UnicodeEncodeError em CLIs)."""

from __future__ import annotations

import sys


def ensure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8")
            except (OSError, ValueError):
                pass
