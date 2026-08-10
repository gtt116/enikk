"""Explicit registration of the hermes built-in tools Enikk depends on.

Hermes 0.18+ discovers built-in tools by globbing ``tools/*.py`` on disk
(``tools.registry.discover_builtin_tools``) and importing what it finds.
Inside a PyInstaller-frozen build there are no ``.py`` files on disk —
modules live in the PYZ archive — so discovery silently registers nothing,
and tools such as ``skill_view`` vanish from the agent schema (the model
then hallucinates calls to a nonexistent ``skill`` tool).

Importing a tool module runs its module-level ``registry.register()``
calls, so the explicit imports below guarantee that every hermes toolset
Enikk enables (see ``ENABLED_TOOLSETS`` in ``eternity.py``) is present in
the registry regardless of filesystem discovery. ``memory`` and ``todo``
are also imported transitively by hermes internals, but keep them here so
the guarantee stays explicit and testable in one place.

Covered by tests/test_hermes_tools.py, which simulates the frozen
condition (discovery disabled) and asserts these tools still register.
"""

import tools.memory_tool          # noqa: F401  toolset "memory"
import tools.session_search_tool  # noqa: F401  toolset "session_search"
import tools.skill_manager_tool   # noqa: F401  toolset "skills" (skill_manage)
import tools.skills_sync          # noqa: F401  bundled-skill seeding (not a tool)
import tools.skills_tool          # noqa: F401  toolset "skills" (skills_list, skill_view)
import tools.todo_tool            # noqa: F401  toolset "todo"

# Hermes-provided toolsets Enikk enables (the enikk-owned "app_controller"
# and "enikk_cron" toolsets register themselves via their own modules).
HERMES_TOOLSETS = ("skills", "memory", "session_search", "todo")

# Tool names those toolsets must put in the registry. Keep in sync with
# HERMES_TOOLSETS / ENABLED_TOOLSETS; the regression test fails loudly if
# a future hermes upgrade renames any of them.
REQUIRED_TOOLS = frozenset({
    "skills_list", "skill_view", "skill_manage",
    "session_search",
    "memory",
    "todo",
})
