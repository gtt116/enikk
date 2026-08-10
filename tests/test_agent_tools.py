"""End-to-end inventory of the tools an enikk agent session actually gets.

Replicates the tool wiring of Eternity.setup() + create_session(): registers
the AppController and cron tools into the real hermes registry, then builds a
real run_agent.AIAgent with eternity.ENABLED_TOOLSETS and asserts the exact
tool list the agent would offer the LLM (agent.valid_tool_names). Building
the agent is offline — no LLM call is made.

Complements tests/test_hermes_tools.py, which covers the frozen-build
registration path: this one checks the final agent schema end to end.

Skipped when hermes-agent is not really installed (conftest mocks missing
modules in minimal environments).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import run_agent

pytestmark = pytest.mark.skipif(
    not isinstance(getattr(run_agent, "AIAgent", None), type),
    reason="hermes-agent not installed (run_agent is mocked)",
)

# Tool names registered by enikk itself (toolsets "app_controller" and
# "enikk_cron"). Keep in sync with @tool-decorated methods in controller.py
# and the schemas in cron/tools.py.
APP_CONTROLLER_TOOLS = frozenset({
    "analyze", "capture_desktop", "click", "close_window", "drag",
    "edit_file", "find_files", "find_window", "hotkey", "launch",
    "list_apps", "list_windows", "move_mouse", "press_key", "read_file",
    "read_image", "register_app", "run_powershell", "scroll", "type_text",
    "unregister_app", "wait", "wait_for", "write_file",
})

CRON_TOOLS = frozenset({
    "cron_create", "cron_delete", "cron_get", "cron_list",
    "cron_pause", "cron_resume", "cron_trigger", "cron_update",
})


@pytest.fixture(scope="module")
def agent():
    """A real AIAgent built the same way Eternity.create_session() builds it."""
    from enikk.controller import AppController
    from enikk.cron import register_cron_tools
    from enikk.eternity import ENABLED_TOOLSETS

    with patch("enikk.controller.capture"), \
         patch("enikk.controller.input_mod"), \
         patch("enikk.controller.window"), \
         patch("enikk.controller.UIParser"):
        config = MagicMock()
        config.workspace.weights_dir = None
        config.workspace.screenshot_max_dim = 1366
        config.workspace.screenshot_dir = "/tmp/screenshots"
        config.apps = {}
        controller = AppController(config)
        controller.register_tools()
    register_cron_tools()

    return run_agent.AIAgent(
        base_url="http://127.0.0.1:9/v1",
        api_key="sk-test",
        provider="openai",
        model="test-model",
        enabled_toolsets=list(ENABLED_TOOLSETS),
        quiet_mode=True,
        save_trajectories=False,
        skip_memory=True,
    )


def _expected_inventory() -> set[str]:
    """Full expected tool list for ENABLED_TOOLSETS in this environment."""
    from enikk.hermes_tools import REQUIRED_TOOLS
    from hermes_state import DEFAULT_DB_PATH

    expected = set(APP_CONTROLLER_TOOLS) | set(CRON_TOOLS) | set(REQUIRED_TOOLS)
    # session_search's check_fn requires the hermes state dir to exist;
    # without it the tool is registered but filtered out of the schema.
    if not DEFAULT_DB_PATH.parent.exists():
        expected.discard("session_search")
    return expected


class TestAgentToolInventory:
    def test_app_controller_tools_present(self, agent):
        missing = APP_CONTROLLER_TOOLS - agent.valid_tool_names
        assert not missing, f"app_controller tools missing: {sorted(missing)}"

    def test_cron_tools_present(self, agent):
        missing = CRON_TOOLS - agent.valid_tool_names
        assert not missing, f"enikk_cron tools missing: {sorted(missing)}"

    def test_hermes_tools_present(self, agent):
        from enikk.hermes_tools import REQUIRED_TOOLS
        from hermes_state import DEFAULT_DB_PATH

        expected = set(REQUIRED_TOOLS)
        if not DEFAULT_DB_PATH.parent.exists():
            expected.discard("session_search")
        missing = expected - agent.valid_tool_names
        assert not missing, f"hermes tools missing: {sorted(missing)}"

    def test_no_tools_outside_enabled_toolsets(self, agent):
        """enabled_toolsets filtering must keep unenabled tools (terminal,
        browser, ...) out of the agent schema."""
        from tools.registry import registry
        from enikk.eternity import ENABLED_TOOLSETS

        for name in sorted(agent.valid_tool_names):
            toolset = registry.get_toolset_for_tool(name)
            assert toolset in ENABLED_TOOLSETS, (
                f"tool {name!r} from toolset {toolset!r} is not in "
                f"ENABLED_TOOLSETS {ENABLED_TOOLSETS}"
            )

    def test_exact_inventory(self, agent):
        """Pin the complete tool list so any change is a conscious update."""
        assert agent.valid_tool_names == _expected_inventory()
