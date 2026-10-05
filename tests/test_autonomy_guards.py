"""Tests for Ravenna auto_apply safety guards."""

from __future__ import annotations

import pytest

from learning_agent.core import agent_autonomy_runner, agent_spec_builder, autonomy_guards
from learning_agent.core.workspace import resolve_path, write_file


def test_infer_patch_mode_from_work_order():
    text = "WORK ORDER — patch cirúrgico. NÃO substitua routes.py inteiro."
    assert autonomy_guards.infer_patch_mode(text) is True


def test_build_spec_marks_surgical_flask_legacy():
    prompt = """
    WORK ORDER patch cirúrgico no Flask REMOTE_APP.
    Arquivos: `remote_app/notification_service.py`, `remote_app/routes.py` (tem ~3400 linhas)
    ```shell
    cd remote_app && py -m pytest tests/test_notification_service.py -q
    ```
    """
    spec = agent_spec_builder.build_spec(prompt, project_root="luis-132-255-110-213")
    assert spec["patchMode"] == "surgical"
    assert "flask-legacy" in spec["semanticRules"]
    assert "remote_app/notification_service.py" in spec["allowedPaths"]
    assert "remote_app/routes.py" in spec["lockedFiles"]
    assert spec["validationCommands"] == ["cd remote_app && py -m pytest tests/test_notification_service.py -q"]


def test_write_guard_blocks_truncation_of_large_file():
    rel = "tests/_scratch_guard/large.py"
    try:
        lines = "\n".join(f"x_{i} = {i}" for i in range(260))
        write_file(rel, lines + "\n")

        reason = autonomy_guards.should_block_write(
            rel,
            "print('tiny')\n",
            spec={"patchMode": "surgical"},
        )
        assert reason is not None
        assert "truncar" in reason.lower() or "menor" in reason.lower()
    finally:
        path = resolve_path(rel)
        path.unlink(missing_ok=True)
        path.parent.rmdir()


def test_apply_write_blocks_records_blocked_truncation():
    rel = "tests/_scratch_guard/applied.py"
    try:
        write_file(rel, "\n".join(f"v{i}={i}" for i in range(240)) + "\n")
        tiny = "```write tests/_scratch_guard/applied.py\nprint('x')\n```"
        result = agent_autonomy_runner.apply_write_blocks(tiny)
        assert result["blockedCount"] == 1
        assert result["changedPaths"] == []
        assert resolve_path(rel).read_text(encoding="utf-8").startswith("v0=")
    finally:
        path = resolve_path(rel)
        path.unlink(missing_ok=True)
        path.parent.rmdir()


def test_surgical_whitelist_blocks_unlisted_path():
    rel_ok = "tests/_scratch_guard/allowed.txt"
    rel_bad = "tests/_scratch_guard/forbidden.txt"
    try:
        spec = {
            "patchMode": "surgical",
            "allowedPaths": ["tests/_scratch_guard/allowed.txt"],
        }
        text = (
            "```write tests/_scratch_guard/allowed.txt\nok\n```\n"
            "```write tests/_scratch_guard/forbidden.txt\nnope\n```"
        )
        result = agent_autonomy_runner.apply_write_blocks(text, spec=spec, allowed_paths=spec["allowedPaths"])
        assert result["blockedCount"] == 1
        assert any(item["path"].endswith("allowed.txt") for item in result["applied"])
        assert not resolve_path(rel_bad).exists()
    finally:
        for rel in (rel_ok, rel_bad):
            path = resolve_path(rel)
            path.unlink(missing_ok=True)
        parent = resolve_path("tests/_scratch_guard")
        if parent.exists():
            parent.rmdir()


def test_build_preflight_context_includes_existing_head():
    rel = "tests/_scratch_guard/preflight.txt"
    try:
        write_file(rel, "alpha\nbeta\ngamma\n")
        ctx = autonomy_guards.build_preflight_context([rel], max_lines=2)
        assert "alpha" in ctx
        assert "beta" in ctx
        assert "preflight" in ctx.lower()
    finally:
        path = resolve_path(rel)
        path.unlink(missing_ok=True)
        path.parent.rmdir()


def test_remoteapp_incident_truncation_regression():
    """Regression from conv REMOTE_APP: stub routes.py must never replace 3k-line file."""
    remote_app_removed = "data/remote-workspaces/remote_app-teste/remote_app/routes.py"
    path = resolve_path(remote_app_removed)
    if not path.is_file():
        pytest.skip("REMOTE_APP cache not present locally")
    old_lines = path.read_text(encoding="utf-8", errors="replace").count("\n")
    assert old_lines > 1000
    stub = "# truncated stub\n@bp.route('/x')\ndef x(): pass\n"
    reason = autonomy_guards.should_block_write(remote_app_removed, stub, spec={"patchMode": "surgical"})
    assert reason is not None
