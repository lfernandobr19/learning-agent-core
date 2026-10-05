"""Testes — catálogo Ravenna Plugins."""

from __future__ import annotations

from learning_agent.core.ravenna_plugins import list_plugins, set_plugin_enabled


def test_list_plugins_includes_builtins():
    plugins = list_plugins()
    ids = {p["id"] for p in plugins}
    assert "ravenna.ravenna-ai" in ids


def test_enable_disable_plugin():
    toggled = set_plugin_enabled("ravenna.sample-tools", False)
    assert toggled["enabled"] is False
    restored = set_plugin_enabled("ravenna.sample-tools", True)
    assert restored["enabled"] is True
