"""Enikk configuration."""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field, fields
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


def enikk_home() -> Path:
    """Enikk home directory for config/data storage."""
    if "ENIKK_HOME" in os.environ:
        return Path(os.environ["ENIKK_HOME"])
    if os.name == "nt":
        return Path(os.environ["LOCALAPPDATA"]) / "Enikk"
    return Path.home() / ".enikk"


CUSTOM_APPS_FILE = enikk_home() / "apps.json"


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
class ModelConfig:
    default: str = ""
    provider: str = ""
    base_url: str = ""
    api_key: str = ""
    max_tokens: int = 65535


@dataclass
class WorkspaceConfig:
    screenshot_dir: str = str(enikk_home() / "screenshots")
    weights_dir: str = str(enikk_home() / "weights")
    screenshot_max_dim: int = 1366
    max_iterations: int = 120


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
class MemoryConfig:
    """Memory/Learning configuration for hermes-agent."""
    memory_enabled: bool = True
    nudge_interval: int = 10  # Trigger memory review every N user messages
    creation_nudge_interval: int = 10  # Trigger skill review every N tool iterations


@dataclass
class Config:
    apps: dict[str, AppConfig] = field(default_factory=dict)
    model: ModelConfig = field(default_factory=ModelConfig)
    workspace: WorkspaceConfig = field(default_factory=WorkspaceConfig)
    im: IMConfig = field(default_factory=IMConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    log_level: str = "INFO"
    language: str = "zh-CN"

    @property
    def config_path(self) -> Path:
        return enikk_home() / "config.yaml"

    # ── Helpers ───────────────────────────────────────────────────────

    def get_app_config(self, app: str) -> AppConfig:
        """Build an AppConfig with name set from config for a given app."""
        ac = self.apps.get(app)
        if ac is None:
            raise KeyError(f"Unknown app '{app}' — register it via API first")
        return AppConfig(
            name=app,
            app_path=ac.app_path,
            launcher_path=ac.launcher_path,
            launch_timeout=ac.launch_timeout,
        )

    def load_apps(self) -> None:
        """Load apps from apps.json into self.apps."""
        if not CUSTOM_APPS_FILE.exists():
            return
        try:
            data = json.loads(CUSTOM_APPS_FILE.read_text())
            for name, info in data.items():
                self.apps[name] = AppConfig(
                    name=name,
                    app_path=info.get("app_path", ""),
                    launcher_path=info.get("launcher_path"),
                    launch_timeout=info.get("launch_timeout", 120),
                )
            logger.info("Loaded %d apps from %s", len(data), CUSTOM_APPS_FILE)
        except Exception as e:
            logger.warning("Failed to load apps: %s", e)

    def _save_apps(self) -> None:
        """Persist apps to apps.json."""
        CUSTOM_APPS_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        for name, ac in self.apps.items():
            data[name] = {
                "app_path": ac.app_path,
                "launcher_path": ac.launcher_path,
                "launch_timeout": ac.launch_timeout,
            }
        CUSTOM_APPS_FILE.write_text(json.dumps(data, indent=2))

    def register_app(self, name: str, exe_path: str) -> AppConfig:
        """Register an app and persist to apps.json."""
        ac = AppConfig(
            name=name,
            app_path=exe_path,
            launcher_path=exe_path,
        )
        self.apps[name] = ac
        self._save_apps()
        logger.info("Registered app: %s -> %s", name, exe_path)
        return ac

    def delete_app(self, name: str) -> bool:
        """Delete an app and persist."""
        if name not in self.apps:
            return False
        del self.apps[name]
        self._save_apps()
        logger.info("Deleted app: %s", name)
        return True

    def update_app(self, name: str, **kwargs) -> AppConfig | None:
        """Update an existing app's fields."""
        if name not in self.apps:
            return None
        ac = self.apps[name]
        for k, v in kwargs.items():
            if hasattr(ac, k) and k != "name":
                setattr(ac, k, v)
        self._save_apps()
        return ac

    # ── Serialization ─────────────────────────────────────────────────

    @classmethod
    def from_yaml(cls, path: str) -> Config:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        cfg = cls()
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
        if "language" in data:
            cfg.language = data["language"]
        if "memory" in data:
            md = data["memory"]
            cfg.memory = MemoryConfig(**{
                k: v for k, v in md.items()
                if k in {f.name for f in fields(MemoryConfig)}
            })
        return cfg

    def to_dict(self) -> dict:
        """Serialize config to dictionary for API responses (excluding apps, which are stored separately)."""
        def dc_to_dict(obj):
            if hasattr(obj, "__dataclass_fields__"):
                return {k: dc_to_dict(v) for k, v in vars(obj).items() if not k.startswith("_") and k != "apps"}
            if isinstance(obj, dict):
                return {k: dc_to_dict(v) for k, v in obj.items()}
            return obj

        return dc_to_dict(self)

    def update_from_dict(self, data: dict) -> None:
        """Update config from dictionary (API request)."""
        if "model" in data:
            for k, v in data["model"].items():
                if hasattr(self.model, k):
                    setattr(self.model, k, v)
        if "workspace" in data:
            for k, v in data["workspace"].items():
                if hasattr(self.workspace, k):
                    setattr(self.workspace, k, v)
        if "log_level" in data:
            self.log_level = data["log_level"]
        if "language" in data:
            self.language = data["language"]
        if "memory" in data:
            for k, v in data["memory"].items():
                if hasattr(self.memory, k):
                    setattr(self.memory, k, v)
        if "im" in data and "platforms" in data["im"]:
            for name, pdata in data["im"]["platforms"].items():
                if name not in self.im.platforms:
                    self.im.platforms[name] = PlatformSettings()
                for k, v in pdata.items():
                    if hasattr(self.im.platforms[name], k):
                        setattr(self.im.platforms[name], k, v)

    def save(self) -> None:
        """Save config to YAML file."""
        data = self.to_dict()
        # Remove empty/default sections to keep config clean
        if not data.get("apps"):
            data.pop("apps", None)
        if not data.get("im", {}).get("platforms"):
            data.pop("im", None)

        path = self.config_path
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
        logger.info("Config saved to %s", path)
