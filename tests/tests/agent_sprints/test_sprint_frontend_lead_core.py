"""Sprint real — frontend-lead: artefatos da IDE."""
from pathlib import Path

from learning_agent.config import PROJECT_ROOT


def test_sprint_frontend_lead_ide_bundle():
    fe = PROJECT_ROOT / "ravenna-ide" / "frontend"
    assert (fe / "package.json").is_file()
    assert (fe / "src" / "pages" / "App.tsx").is_file()
    assert (fe / "src" / "utils" / "websocket.ts").is_file()
