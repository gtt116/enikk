"""Unit tests for enikk.config."""

import os
import tempfile

from enikk.config import (
    AppConfig,
    Config,
    ModelConfig,
    ServerConfig,
    WorkspaceConfig,
)


def _write_yaml(content: str) -> str:
    """Write a YAML string to a temp file and return the path."""
    fd, path = tempfile.mkstemp(suffix=".yaml")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)
    return path


# ── Sub-config defaults ──────────────────────────────────────────────


class TestAppConfig:
    def test_defaults(self):
        ac = AppConfig()
        assert ac.app_path == ""
        assert ac.launcher_path is None
        assert ac.launch_timeout == 120

    def test_app_name(self):
        ac = AppConfig(app_path=r"C:\foo\bar\baz.exe")
        assert ac.app_name == "baz.exe"

    def test_launcher_app_name_none(self):
        ac = AppConfig(launcher_path=None)
        assert ac.launcher_exe_name is None

    def test_launcher_app_name(self):
        ac = AppConfig(launcher_path=r"C:\foo\launcher.exe")
        assert ac.launcher_exe_name == "launcher.exe"


class TestServerConfig:
    def test_defaults(self):
        sc = ServerConfig()
        assert sc.host == "127.0.0.1"
        assert sc.port == 18931


class TestModelConfig:
    def test_defaults(self):
        mc = ModelConfig()
        assert mc.default == ""
        assert mc.provider == ""
        assert mc.base_url == ""
        assert mc.api_key == ""
        assert mc.max_tokens == 65535


class TestWorkspaceConfig:
    def test_defaults(self):
        wc = WorkspaceConfig()
        assert "screenshots" in wc.screenshot_dir
        assert "weights" in wc.weights_dir
        assert wc.save_screenshots is False
        assert wc.screenshot_max_dim == 1366


# ── from_yaml ────────────────────────────────────────────────────────


class TestFromYaml:
    def test_full(self):
        path = _write_yaml("""
apps:
  nikke:
    app_path: "D:\\\\nikke\\\\game.exe"
    launcher_path: "D:\\\\nikke\\\\launcher.exe"
    launch_timeout: 60
server:
  host: "0.0.0.0"
  port: 8080
model:
  default: "gpt-4"
  provider: "openai"
  base_url: "https://api.openai.com/v1"
  api_key: "sk-test"
  max_tokens: 64000
workspace:
  screenshot_dir: "./ss"
  weights_dir: "./w"
  save_screenshots: true
""")
        try:
            cfg = Config.from_yaml(path)
        finally:
            os.unlink(path)

        ac = cfg.apps["nikke"]
        assert ac.app_path == r"D:\nikke\game.exe"
        assert ac.launcher_path == r"D:\nikke\launcher.exe"
        assert ac.launch_timeout == 60
        assert cfg.server.host == "0.0.0.0"
        assert cfg.server.port == 8080
        assert cfg.model.default == "gpt-4"
        assert cfg.model.provider == "openai"
        assert cfg.model.api_key == "sk-test"
        assert cfg.model.max_tokens == 64000
        assert cfg.workspace.save_screenshots is True

    def test_legacy_games_key(self):
        """Legacy 'games' key in YAML still works (backward compat)."""
        path = _write_yaml("""
games:
  nikke:
    game_path: "D:\\\\nikke\\\\game.exe"
    launcher_path: "D:\\\\nikke\\\\launcher.exe"
""")
        try:
            cfg = Config.from_yaml(path)
        finally:
            os.unlink(path)

        # Legacy game_path maps to app_path
        ac = cfg.apps["nikke"]
        assert ac.app_path == r"D:\nikke\game.exe"
        assert ac.launcher_path == r"D:\nikke\launcher.exe"

    def test_unknown_keys_ignored(self):
        path = _write_yaml("""
apps:
  nikke:
    app_path: "C:\\\\g.exe"
    unknown_field: should_be_ignored
server:
  host: "127.0.0.1"
  bogus: 42
""")
        try:
            cfg = Config.from_yaml(path)
        finally:
            os.unlink(path)

        assert cfg.apps["nikke"].app_path == r"C:\g.exe"
        assert cfg.server.host == "127.0.0.1"

    def test_empty_data(self):
        path = _write_yaml("")
        try:
            cfg = Config.from_yaml(path)
        finally:
            os.unlink(path)
        assert cfg.apps == {}


# ── Config defaults ──────────────────────────────────────────────────


def test_config_defaults():
    cfg = Config()
    assert isinstance(cfg.server, ServerConfig)
    assert isinstance(cfg.model, ModelConfig)
    assert isinstance(cfg.workspace, WorkspaceConfig)
    assert cfg.apps == {}


def test_apps_access():
    cfg = Config()
    cfg.apps["myapp"] = AppConfig(app_path=r"D:\my.exe")
    assert cfg.apps["myapp"].app_path == r"D:\my.exe"
    assert cfg.apps["myapp"].app_name == "my.exe"
