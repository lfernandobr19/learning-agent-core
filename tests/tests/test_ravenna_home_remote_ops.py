from pathlib import Path

from learning_agent.core import agent_spec_builder, autonomy_guards
from learning_agent.core.ravenna_home_remote_ops import (
    BUILD_CMD,
    check_frontend_integration,
    is_ravenna_home_remote_command,
)


def test_deploy_spec_uses_docker_not_npm():
    spec = agent_spec_builder.build_spec(
        "rh-07-cursor-bar barra equivalente cursor — 3 abas",
        project_root="ravenna-home/frontend",
    )
    assert spec.get("ravennaHomeRemoteValidation") is True
    joined = " ".join(spec.get("validationCommands") or [])
    assert "ravenna-home-web" in joined
    assert "npm run build" not in joined


def test_remote_command_detection():
    assert is_ravenna_home_remote_command(BUILD_CMD)
    assert is_ravenna_home_remote_command("cd frontend && npm run build")
    assert not is_ravenna_home_remote_command("py -m pytest backend/tests -q")


def test_forbidden_app_js_blocked():
    reason = autonomy_guards.should_block_write(
        "ravenna-home/frontend/src/App.js",
        "export default function App() {}",
        spec={"forbiddenPaths": ["src/App.js", "src/App.jsx"]},
    )
    assert reason is not None
    assert "proibido" in reason.lower()


def test_integration_check_flags_broken_app(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "App.js").write_text("export default function App() {}", encoding="utf-8")
    (src / "App.tsx").write_text(
        "import Layout from '../components/Layout';\nexport default function App() { return <Layout />; }\n",
        encoding="utf-8",
    )
    (tmp_path / "package.json").write_text('{"name":"ravenna-ide"}', encoding="utf-8")
    failures = check_frontend_integration(tmp_path)
    assert any("App.js" in item for item in failures)
    assert any(
        "useState" in item or "abas" in item or "Layout" in item or "import" in item.lower()
        for item in failures
    )
    assert any("package.json" in item for item in failures)
