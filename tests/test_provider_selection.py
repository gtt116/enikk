"""Tests for provider selection feature."""

from unittest.mock import patch, MagicMock


class TestEffectiveProvider:
    """Tests for ModelConfig.effective_provider property."""

    def test_empty_provider(self):
        """Empty provider should return empty string."""
        from enikk.config import ModelConfig
        mc = ModelConfig(provider="")
        assert mc.effective_provider == ""

    def test_custom_prefix_preserved(self):
        """Provider with custom: prefix should be preserved."""
        from enikk.config import ModelConfig
        mc = ModelConfig(provider="custom:myprovider")
        assert mc.effective_provider == "custom:myprovider"

    def test_custom_exact_preserved(self):
        """Provider 'custom' should be preserved."""
        from enikk.config import ModelConfig
        mc = ModelConfig(provider="custom")
        assert mc.effective_provider == "custom"

    @patch('hermes_cli.auth.PROVIDER_REGISTRY')
    def test_builtin_provider_no_custom_url(self, mock_registry):
        """Built-in provider without custom base_url should use as-is."""
        from enikk.config import ModelConfig
        # Mock a built-in provider
        mock_cfg = MagicMock()
        mock_cfg.inference_base_url = "https://api.openai.com/v1"
        mock_registry.get.return_value = mock_cfg

        mc = ModelConfig(
            provider="openai",
            api_key="sk-test",
            base_url=""  # No custom base_url
        )
        assert mc.effective_provider == "openai"

    @patch('hermes_cli.auth.PROVIDER_REGISTRY')
    def test_builtin_provider_matching_url(self, mock_registry):
        """Built-in provider with matching base_url should use as-is."""
        from enikk.config import ModelConfig
        mock_cfg = MagicMock()
        mock_cfg.inference_base_url = "https://api.openai.com/v1"
        mock_registry.get.return_value = mock_cfg

        mc = ModelConfig(
            provider="openai",
            api_key="sk-test",
            base_url="https://api.openai.com/v1"  # Matches built-in
        )
        assert mc.effective_provider == "openai"

    @patch('hermes_cli.auth.PROVIDER_REGISTRY')
    def test_builtin_provider_custom_url(self, mock_registry):
        """Built-in provider with custom base_url should add custom: prefix."""
        from enikk.config import ModelConfig
        mock_cfg = MagicMock()
        mock_cfg.inference_base_url = "https://api.openai.com/v1"
        mock_registry.get.return_value = mock_cfg

        mc = ModelConfig(
            provider="openai",
            api_key="sk-test",
            base_url="https://my-proxy.com/v1"  # Custom base_url
        )
        assert mc.effective_provider == "custom:openai"

    @patch('hermes_cli.auth.PROVIDER_REGISTRY')
    def test_unknown_provider_with_credentials(self, mock_registry):
        """Unknown provider with credentials should add custom: prefix."""
        from enikk.config import ModelConfig
        mock_registry.get.return_value = None

        mc = ModelConfig(
            provider="myprovider",
            api_key="test-key",
            base_url="https://my-endpoint.com/v1"
        )
        assert mc.effective_provider == "custom:myprovider"

    @patch('hermes_cli.auth.PROVIDER_REGISTRY')
    def test_unknown_provider_no_credentials(self, mock_registry):
        """Unknown provider without credentials should return as-is."""
        from enikk.config import ModelConfig
        mock_registry.get.return_value = None

        mc = ModelConfig(provider="myprovider")
        assert mc.effective_provider == "myprovider"
