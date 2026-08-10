"""Regression test: hermes tools must register without filesystem discovery.

Hermes 0.18+ finds built-in tools by globbing ``tools/*.py`` on disk
(``tools.registry.discover_builtin_tools``). Inside a PyInstaller-frozen
build no ``.py`` files exist on disk (modules live in the PYZ archive), so
discovery silently registers nothing — ``skills_list``/``skill_view``/
``session_search`` vanished from the agent schema and the model fell back
to hallucinating a nonexistent ``skill`` tool.

``enikk/hermes_tools.py`` counters this by importing every hermes tool
module Enikk needs explicitly. A normal in-process assertion cannot catch
the original bug (discovery works fine on a dev checkout where the ``.py``
files exist), so this test simulates the frozen condition in a subprocess:
it patches ``discover_builtin_tools`` to a no-op BEFORE anything imports
``model_tools``, then checks that ``enikk.hermes_tools`` alone puts every
required tool into the registry.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys

import pytest

# Runs in a fresh subprocess so model_tools has not triggered discovery yet.
# The patch must land before model_tools binds discover_builtin_tools.
_CHECK_SCRIPT = """
import sys

import tools.registry

# Simulate a PyInstaller-frozen build: the tools/*.py glob finds nothing,
# so discovery registers no built-in tools at all.
tools.registry.discover_builtin_tools = lambda tools_dir=None: []

import model_tools  # noqa: F401,E402  runs the patched (no-op) discovery

from enikk import hermes_tools  # noqa: E402

registered = set(tools.registry.registry.get_tool_to_toolset_map())

# 1) Hard contract: the tools Enikk's prompt/schema rely on.
missing = set(hermes_tools.REQUIRED_TOOLS - registered)

# 2) Forward-looking contract: whatever the enabled hermes toolsets resolve
#    to in this hermes version must also be registered. Catches hermes
#    upgrades that add tools to an enabled toolset without us noticing.
from toolsets import resolve_toolset, validate_toolset  # noqa: E402

for toolset in hermes_tools.HERMES_TOOLSETS:
    if not validate_toolset(toolset):
        missing.add(f"<toolset '{toolset}' no longer exists>")
        continue
    missing.update(set(resolve_toolset(toolset)) - registered)

if missing:
    print("MISSING: " + ", ".join(sorted(missing)))
    sys.exit(1)
print("OK")
"""


@pytest.mark.skipif(
    importlib.util.find_spec("model_tools") is None,
    reason="hermes-agent not installed",
)
def test_hermes_tools_register_without_filesystem_discovery(tmp_path):
    """With discovery disabled (frozen-build condition), enikk.hermes_tools
    must still register every tool Enikk enables."""
    env = os.environ.copy()
    env["HERMES_HOME"] = str(tmp_path / "hermes-home")
    result = subprocess.run(
        [sys.executable, "-c", _CHECK_SCRIPT],
        capture_output=True,
        text=True,
        env=env,
        timeout=180,
    )
    assert result.returncode == 0, (
        "hermes tools failed to register with filesystem discovery disabled "
        "(this is how PyInstaller-frozen builds behave — check explicit "
        f"imports in enikk/hermes_tools.py):\n{result.stdout}\n{result.stderr}"
    )
