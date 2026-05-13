"""Enikk configuration."""
import os
from dataclasses import dataclass, field, fields
from pathlib import Path

import yaml


GAME_PROCESS = {'intl': 'nikke.exe', 'hmt': 'nikke.exe'}
LAUNCHER_PROCESS = {'intl': 'nikke_launcher.exe', 'hmt': 'nikke_launcher_hmt.exe'}
WINDOW_CLASS = 'UnityWndClass'
LAUNCHER_CLASS = 'TWINCONTROL'


@dataclass
class Config:
    # Launcher and game paths
    launcher_path: str = r"C:\Program Files\NIKKE\launcher\nikke_launcher.exe"
    game_path: str = r"C:\Program Files\NIKKE\NIKKE.exe"
    client_type: str = "intl"  # intl or hmt
    window_class: str = WINDOW_CLASS
    window_title: str = "NIKKE"
    launch_timeout: int = 120
    host: str = "127.0.0.1"
    port: int = 18931  # HTTP API (legacy)
    ws_port: int = 18932  # WebSocket server (new)
    save_screenshots: bool = False
    screenshot_dir: str = str(Path(__file__).resolve().parent.parent / "screenshots")
    weights_dir: str = str(Path(__file__).resolve().parent.parent / "weights")

    # Agent defaults
    agent_model: str = "qwen3.6-plus"
    agent_base_url: str = ""
    agent_api_key: str = ""

    @classmethod
    def from_yaml(cls, path: str) -> "Config":
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        valid = {f.name for f in fields(cls)}
        data = {k: v for k, v in data.items() if k in valid}
        return cls(**data)

    @classmethod
    def from_env(cls) -> "Config":
        overrides = {}
        if v := os.environ.get("ENIKK_LAUNCHER_PATH"):
            overrides["launcher_path"] = v
        if v := os.environ.get("ENIKK_GAME_PATH"):
            overrides["game_path"] = v
        if v := os.environ.get("ENIKK_PORT"):
            overrides["port"] = int(v)
        if v := os.environ.get("ENIKK_HOST"):
            overrides["host"] = v
        return cls(**overrides)

    @property
    def game_process_name(self) -> str:
        return GAME_PROCESS.get(self.client_type, 'nikke.exe')

    @property
    def launcher_process_name(self) -> str:
        return LAUNCHER_PROCESS.get(self.client_type, 'nikke_launcher.exe')
