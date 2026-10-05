"""Testes — fetch market data finance-lead."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from learning_agent.config import PROJECT_ROOT


def test_fetch_market_data_fixture_fallback():
    script = PROJECT_ROOT / "agents" / "projects" / "finance-lead" / "scripts" / "fetch_market_data.py"
    proc = subprocess.run(
        [sys.executable, str(script), "PETR4", "--source", "fixture"],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr[-300:]
    assert "fixture" in proc.stdout
