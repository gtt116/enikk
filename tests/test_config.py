"""Unit tests for enikk.config."""

import os
import tempfile

from enikk.config import (
    AppConfig,
    Config,
    ModelConfig,
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


class TestModelConfig:
    def test_defaults(self):
        mc = ModelConfig()
        assert mc.default == ""
        assert mc.provider == ""
        assert mc.base_url == ""
        assert mc.api_key == ""
        assert mc.max_tokens == 65535
        assert mc.context_length == 262144

    def test_context_length(self):
        mc = ModelConfig(context_length=128000)
        assert mc.context_length == 128000


class TestModelConfigEffectiveProvider:
    """Tests for ModelConfig.effective_provider property."""

    def test_empty_provider(self):
        """When provider is empty, effective_provider returns empty string."""
        mc = ModelConfig(provider="")
        assert mc.effective_provider == ""

    def test_no_base_url_or_api_key(self):
        """When base_url and api_key are not configured, return original provider."""
        mc = ModelConfig(provider="openrouter")
        assert mc.effective_provider == "openrouter"

    def test_only_base_url(self):
        """When only base_url is configured, return original provider."""
        mc = ModelConfig(
            provider="alibaba",
            base_url="https://dashscope.aliyuncs.com/v1"
        )
        assert mc.effective_provider == "alibaba"

    def test_only_api_key(self):
        """When only api_key is configured, return original provider."""
        mc = ModelConfig(
            provider="alibaba",
            api_key="sk-test"
        )
        assert mc.effective_provider == "alibaba"

    def test_both_base_url_and_api_key(self):
        """When both base_url and api_key are configured, prefix with 'custom:'."""
        mc = ModelConfig(
            provider="alibaba",
            base_url="https://dashscope.aliyuncs.com/v1",
            api_key="sk-test"
        )
        assert mc.effective_provider == "custom:alibaba"

    def test_already_has_custom_prefix(self):
        """When provider already has 'custom:' prefix, don't add again."""
        mc = ModelConfig(
            provider="custom:myprovider",
            base_url="http://localhost:11434",
            api_key="xxx"
        )
        assert mc.effective_provider == "custom:myprovider"

    def test_provider_is_custom(self):
        """When provider is exactly 'custom', don't add prefix."""
        mc = ModelConfig(
            provider="custom",
            base_url="http://localhost:11434",
            api_key="xxx"
        )
        assert mc.effective_provider == "custom"


class TestWorkspaceConfig:
    def test_defaults(self):
        wc = WorkspaceConfig()
        assert "screenshots" in wc.screenshot_dir
        assert "weights" in wc.weights_dir
        assert wc.screenshot_max_dim == 1366
        assert wc.max_iterations == 120


# ── from_yaml ────────────────────────────────────────────────────────


class TestFromYaml:
    def test_full(self):
        path = _write_yaml("""
model:
  default: "gpt-4"
  provider: "openai"
  base_url: "https://api.openai.com/v1"
  api_key: "sk-test"
  max_tokens: 64000
  context_length: 128000
workspace:
  screenshot_dir: "./ss"
  weights_dir: "./w"
  max_iterations: 1200
""")
        try:
            cfg = Config.from_yaml(path)
        finally:
            os.unlink(path)

        assert cfg.model.default == "gpt-4"
        assert cfg.model.provider == "openai"
        assert cfg.model.api_key == "sk-test"
        assert cfg.model.max_tokens == 64000
        assert cfg.model.context_length == 128000
        assert cfg.workspace.max_iterations == 1200

    def test_unknown_keys_ignored(self):
        path = _write_yaml("""
model:
  default: "gpt-4"
server:
  host: "127.0.0.1"
  bogus: 42
""")
        try:
            cfg = Config.from_yaml(path)
        finally:
            os.unlink(path)

        assert cfg.model.default == "gpt-4"

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
    assert isinstance(cfg.model, ModelConfig)
    assert isinstance(cfg.workspace, WorkspaceConfig)
    assert cfg.apps == {}


def test_apps_access():
    cfg = Config()
    cfg.apps["myapp"] = AppConfig(app_path=r"D:\my.exe")
    assert cfg.apps["myapp"].app_path == r"D:\my.exe"
    assert cfg.apps["myapp"].app_name == "my.exe"


# ── Apps persistence ──────────────────────────────────────────────────


def test_save_and_load_apps(tmp_path, monkeypatch):
    """Apps are persisted to apps.json and can be reloaded."""
    import json
    apps_file = tmp_path / "apps.json"
    monkeypatch.setattr("enikk.config.CUSTOM_APPS_FILE", apps_file)

    cfg = Config()
    cfg.apps["test"] = AppConfig(
        name="test",
        app_path=r"C:\test.exe",
        launcher_path=r"C:\launcher.exe",
        launch_timeout=90,
    )
    cfg._save_apps()

    assert apps_file.exists()
    data = json.loads(apps_file.read_text())
    assert "test" in data
    assert data["test"]["app_path"] == r"C:\test.exe"
    assert data["test"]["launcher_path"] == r"C:\launcher.exe"
    assert data["test"]["launch_timeout"] == 90

    # Load into a new config
    cfg2 = Config()
    cfg2.load_apps()
    assert "test" in cfg2.apps
    assert cfg2.apps["test"].app_path == r"C:\test.exe"
    assert cfg2.apps["test"].launcher_path == r"C:\launcher.exe"
    assert cfg2.apps["test"].launch_timeout == 90


def test_register_app_persists(tmp_path, monkeypatch):
    """register_app() persists to apps.json."""
    import json
    apps_file = tmp_path / "apps.json"
    monkeypatch.setattr("enikk.config.CUSTOM_APPS_FILE", apps_file)

    cfg = Config()
    cfg.register_app("myapp", r"D:\my.exe")

    assert "myapp" in cfg.apps
    assert apps_file.exists()
    data = json.loads(apps_file.read_text())
    assert data["myapp"]["app_path"] == r"D:\my.exe"


def test_delete_app_persists(tmp_path, monkeypatch):
    """delete_app() removes from apps.json."""
    import json
    apps_file = tmp_path / "apps.json"
    monkeypatch.setattr("enikk.config.CUSTOM_APPS_FILE", apps_file)

    cfg = Config()
    cfg.register_app("app1", r"D:\a1.exe")
    cfg.register_app("app2", r"D:\a2.exe")
    assert apps_file.exists()

    cfg.delete_app("app1")
    data = json.loads(apps_file.read_text())
    assert "app1" not in data
    assert "app2" in data
    assert "app1" not in cfg.apps
    assert "app2" in cfg.apps


def test_update_app_persists(tmp_path, monkeypatch):
    """update_app() persists changes to apps.json."""
    import json
    apps_file = tmp_path / "apps.json"
    monkeypatch.setattr("enikk.config.CUSTOM_APPS_FILE", apps_file)

    cfg = Config()
    cfg.register_app("test", r"D:\old.exe")

    cfg.update_app("test", app_path=r"D:\new.exe", launch_timeout=60)
    data = json.loads(apps_file.read_text())
    assert data["test"]["app_path"] == r"D:\new.exe"
    assert data["test"]["launch_timeout"] == 60
    assert cfg.apps["test"].app_path == r"D:\new.exe"


def test_to_dict_excludes_apps():
    """to_dict() should not include apps (they're stored separately)."""
    cfg = Config()
    cfg.apps["test"] = AppConfig(app_path=r"D:\test.exe")
    d = cfg.to_dict()
    assert "apps" not in d
    assert "model" in d
