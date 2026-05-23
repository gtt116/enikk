"""Unit tests for enikk.config."""

import os
import tempfile

from enikk.config import (
    Config,
    GameConfig,
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


class TestGameConfig:
    def test_defaults(self):
        gc = GameConfig()
        assert gc.game_path == ""
        assert gc.launcher_path is None
        assert gc.launch_timeout == 120

    def test_game_name(self):
        gc = GameConfig(game_path=r"C:\foo\bar\baz.exe")
        assert gc.game_name == "baz.exe"

    def test_launcher_game_name_none(self):
        gc = GameConfig(launcher_path=None)
        assert gc.launcher_exe_name is None

    def test_launcher_game_name(self):
        gc = GameConfig(launcher_path=r"C:\foo\launcher.exe")
        assert gc.launcher_exe_name == "launcher.exe"


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


# ── from_yaml ────────────────────────────────────────────────────────


class TestFromYaml:
    def test_full(self):
        path = _write_yaml("""
games:
  nikke:
    game_path: "D:\\\\nikke\\\\game.exe"
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
active_game: nikke
""")
        try:
            cfg = Config.from_yaml(path)
        finally:
            os.unlink(path)

        gc = cfg.games["nikke"]
        assert gc.game_path == r"D:\nikke\game.exe"
        assert gc.launcher_path == r"D:\nikke\launcher.exe"
        assert gc.launch_timeout == 60
        assert cfg.server.host == "0.0.0.0"
        assert cfg.server.port == 8080
        assert cfg.model.default == "gpt-4"
        assert cfg.model.provider == "openai"
        assert cfg.model.api_key == "sk-test"
        assert cfg.model.max_tokens == 64000
        assert cfg.workspace.save_screenshots is True

    def test_unknown_keys_ignored(self):
        path = _write_yaml("""
games:
  nikke:
    game_path: "C:\\\\g.exe"
    unknown_field: should_be_ignored
server:
  host: "127.0.0.1"
  bogus: 42
""")
        try:
            cfg = Config.from_yaml(path)
        finally:
            os.unlink(path)

        assert cfg.games["nikke"].game_path == r"C:\g.exe"
        assert cfg.server.host == "127.0.0.1"

    def test_empty_data(self):
        path = _write_yaml("")
        try:
            cfg = Config.from_yaml(path)
        finally:
            os.unlink(path)
        assert cfg.games == {}

    def test_active_game_ignored(self):
        """active_game key in YAML is no longer used."""
        path = _write_yaml("""
games:
  nikke:
    game_path: "C:\\\\g.exe"
active_game: some_other
""")
        try:
            cfg = Config.from_yaml(path)
        finally:
            os.unlink(path)
        assert "nikke" in cfg.games


# ── Config defaults ──────────────────────────────────────────────────


def test_config_defaults():
    cfg = Config()
    assert isinstance(cfg.server, ServerConfig)
    assert isinstance(cfg.model, ModelConfig)
    assert isinstance(cfg.workspace, WorkspaceConfig)
    assert cfg.games == {}


def test_games_access():
    cfg = Config()
    cfg.games["mygame"] = GameConfig(game_path=r"D:\my.exe")
    assert cfg.games["mygame"].game_path == r"D:\my.exe"
    assert cfg.games["mygame"].game_name == "my.exe"