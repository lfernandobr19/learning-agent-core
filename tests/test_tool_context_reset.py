"""ContextVar reset must not raise when generator closes in another context."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from learning_agent.core import agent_tools


@patch.object(agent_tools, "_TOOL_PROJECT_ROOT")
def test_reset_tool_project_root_swallows_cross_context_value_error(mock_var: MagicMock) -> None:
    mock_var.reset.side_effect = ValueError(
        "<Token var=<ContextVar name='tool_project_root' default=None at 0x0> "
        "at 0x0> was created in a different Context"
    )
    agent_tools.reset_tool_project_root(MagicMock())
    mock_var.set.assert_called_once_with(None)


@patch.object(agent_tools, "_TOOL_ALLOWLIST")
def test_reset_tool_allowlist_swallows_cross_context_value_error(mock_var: MagicMock) -> None:
    mock_var.reset.side_effect = ValueError(
        "<Token var=<ContextVar name='tool_allowlist' default=None at 0x0> "
        "at 0x0> was created in a different Context"
    )
    agent_tools.reset_tool_allowlist(MagicMock())
    mock_var.set.assert_called_once_with(None)
