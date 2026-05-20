"""Enikk configuration."""
from __future__ import annotations

from dataclasses import dataclass, field, fields
from pathlib import Path

import yaml


@dataclass
class GameConfig:
    """Per-game configuration, mirrors GameProfile fields."""

    game_path: str = r"C:\Program Files\NIKKE\NIKKE.exe"
    launcher_path: str | None = r"C:\Program Files\NIKKE\launcher\nikke_launcher.exe"
    game_window_class: str = "UnityWndClass"
    launcher_window_class: str | None = "TWINCONTROL"
    launch_timeout: int = 120

    @property
    def game_name(self) -> str:
        return Path(self.game_path).name

    @property
    def launcher_game_name(self) -> str | None:
        if not self.launcher_path:
            return None
        return Path(self.launcher_path).name


@dataclass
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 18931  # HTTP API
    ws_port: int = 18932  # WebSocket


@dataclass
class ModelConfig:
    default: str = "deepseek-v4-pro"
    provider: str = ""
    base_url: str = ""
    api_key: str = ""
    max_tokens: int = 128000


@dataclass
class WorkspaceConfig:
    screenshot_dir: str = str(Path(__file__).resolve().parent.parent / "screenshots")
    weights_dir: str = str(Path(__file__).resolve().parent.parent / "weights")
    save_screenshots: bool = False


@dataclass
class Config:
    games: dict[str, GameConfig] = field(default_factory=dict)
    server: ServerConfig = field(default_factory=ServerConfig)
    model: ModelConfig = field(default_factory=ModelConfig)
    workspace: WorkspaceConfig = field(default_factory=WorkspaceConfig)

    # ── Serialization ─────────────────────────────────────────────────

    @classmethod
    def from_yaml(cls, path: str) -> Config:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        cfg = cls()
        if "games" in data:
            for name, gd in data["games"].items():
                cfg.games[name] = GameConfig(**{
                    k: v for k, v in gd.items()
                    if k in {f.name for f in fields(GameConfig)}
                })
        if "server" in data:
            sd = data["server"]
            cfg.server = ServerConfig(**{
                k: v for k, v in sd.items()
                if k in {f.name for f in fields(ServerConfig)}
            })
        if "model" in data:
            md = data["model"]
            cfg.model = ModelConfig(**{
                k: v for k, v in md.items()
                if k in {f.name for f in fields(ModelConfig)}
            })
        if "workspace" in data:
            wd = data["workspace"]
            cfg.workspace = WorkspaceConfig(**{
                k: v for k, v in wd.items()
                if k in {f.name for f in fields(WorkspaceConfig)}
            })
        return cfg