"""Enikk configuration."""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field, fields
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


def _enikk_home() -> Path:
    """Enikk home directory for config/data storage."""
    if os.name == "nt":
        return Path(os.environ["LOCALAPPDATA"]) / "Enikk"
    return Path.home() / ".enikk"


CUSTOM_APPS_FILE = _enikk_home() / "custom_apps.json"


@dataclass
class AppConfig:
    """Per-app configuration."""

    name: str = ""
    app_path: str = ""
    launcher_path: str | None = None
    launch_timeout: int = 120

    @property
    def app_name(self) -> str:
        return Path(self.app_path).name

    @property
    def launcher_exe_name(self) -> str | None:
        if not self.launcher_path:
            return None
        return Path(self.launcher_path).name


@dataclass
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 18931  # HTTP API


@dataclass
class ModelConfig:
    default: str = ""
    provider: str = ""
    base_url: str = ""
    api_key: str = ""
    max_tokens: int = 65535


@dataclass
class WorkspaceConfig:
    screenshot_dir: str = str(Path(__file__).resolve().parent.parent / "screenshots")
    weights_dir: str = str(Path(__file__).resolve().parent.parent / "weights")
    save_screenshots: bool = False
    screenshot_max_dim: int = 1366


@dataclass
class PlatformSettings:
    """Per-platform IM settings."""
    enabled: bool = False
    token: str = ""  # bot token (Telegram, Discord, Slack)
    extra: dict = field(default_factory=dict)  # platform-specific (app_id, client_secret, etc.)


@dataclass
class IMConfig:
    """IM platform integration (Telegram, Discord, etc.)."""
    platforms: dict[str, PlatformSettings] = field(default_factory=dict)

    @property
    def active_platform(self) -> tuple[str, PlatformSettings] | None:
        """Return the first enabled (platform_name, settings) pair."""
        for name, ps in self.platforms.items():
            if ps.enabled:
                return name, ps
        return None


@dataclass
class Config:
    apps: dict[str, AppConfig] = field(default_factory=dict)
    server: ServerConfig = field(default_factory=ServerConfig)
    model: ModelConfig = field(default_factory=ModelConfig)
    workspace: WorkspaceConfig = field(default_factory=WorkspaceConfig)
    im: IMConfig = field(default_factory=IMConfig)
    log_level: str = "INFO"

    # ── Helpers ───────────────────────────────────────────────────────

    def build_profile(self, app: str) -> AppConfig:
        """Build an AppConfig with name set from config for a given app."""
        ac = self.apps.get(app)
        if ac is None:
            raise KeyError(f"Unknown app '{app}' — add it to config.yaml under apps:")
        return AppConfig(
            name=app,
            app_path=ac.app_path,
            launcher_path=ac.launcher_path,
            launch_timeout=ac.launch_timeout,
        )

    def register_app(self, name: str, exe_path: str) -> AppConfig:
        """Register a custom app and persist to custom_apps.json."""
        ac = AppConfig(
            name=name,
            app_path=exe_path,
            launcher_path=exe_path,
        )
        self.apps[name] = ac
        self._persist_custom_app(name, exe_path)
        logger.info("Registered app: %s -> %s", name, exe_path)
        return ac

    def _persist_custom_app(self, name: str, exe_path: str) -> None:
        """Append to custom_apps.json."""
        CUSTOM_APPS_FILE.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = json.loads(CUSTOM_APPS_FILE.read_text()) if CUSTOM_APPS_FILE.exists() else {}
        except Exception:
            data = {}
        data[name] = {"exe": exe_path}
        CUSTOM_APPS_FILE.write_text(json.dumps(data, indent=2))

    def load_custom_apps(self) -> None:
        """Load custom apps from custom_apps.json into self.apps."""
        if not CUSTOM_APPS_FILE.exists():
            return
        try:
            data = json.loads(CUSTOM_APPS_FILE.read_text())
            for name, info in data.items():
                if name not in self.apps:
                    exe = info.get("exe", "")
                    self.apps[name] = AppConfig(
                        name=name,
                        app_path=exe,
                        launcher_path=exe,
                    )
                    logger.info("Loaded custom app: %s", name)
        except Exception as e:
            logger.warning("Failed to load custom apps: %s", e)

    # ── Serialization ─────────────────────────────────────────────────

    @classmethod
    def from_yaml(cls, path: str) -> Config:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        cfg = cls()
        # Support both "apps" and legacy "games" keys
        apps_data = data.get("apps") or data.get("games")
        if apps_data:
            valid_fields = {f.name for f in fields(AppConfig)}
            for name, gd in apps_data.items():
                # Map legacy game_path → app_path
                if "game_path" in gd and "app_path" not in gd:
                    gd["app_path"] = gd.pop("game_path")
                cfg.apps[name] = AppConfig(**{
                    k: v for k, v in gd.items()
                    if k in valid_fields
                }, name=name)
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
        if "im" in data:
            im_data = data["im"]
            platforms = {}
            if "platforms" in im_data:
                for name, pdata in im_data["platforms"].items():
                    platforms[name] = PlatformSettings(**{
                        k: v for k, v in pdata.items()
                        if k in {f.name for f in fields(PlatformSettings)}
                    })
            cfg.im = IMConfig(platforms=platforms)
        if "log_level" in data:
            cfg.log_level = data["log_level"]
        return cfg
