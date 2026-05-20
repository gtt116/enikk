"""Game profile model."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GameProfile:
    """Minimal game configuration used by runtime services."""

    name: str
    game_path: str
    launcher_path: str | None = None
    game_window_class: str = "UnityWndClass"
    launcher_window_class: str | None = None

    @property
    def game_name(self) -> str:
        return Path(self.game_path).name

    @property
    def launcher_exe_name(self) -> str | None:
        if not self.launcher_path:
            return None
        return Path(self.launcher_path).name