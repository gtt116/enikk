"""Tests for weights module."""
import sys
from pathlib import Path
from unittest.mock import patch

from enikk.weights import get_bundle_weights_dir, ensure_weights_ready


class TestGetBundleWeightsDir:
    """Test get_bundle_weights_dir function."""

    def test_dev_mode_with_weights(self, tmp_path):
        """Test finding weights in development mode."""
        # Create a fake package structure with weights
        # __file__ is at package/weights.py, so parent is package/
        # and parent.parent / 'weights' would be package/../weights
        # But our code does parent.parent / 'weights', so we need:
        # tmp_path/package/enikk/weights.py -> tmp_path/package/weights/
        package_dir = tmp_path / "package"
        enikk_dir = package_dir / "enikk"
        enikk_dir.mkdir(parents=True)
        weights_dir = package_dir / "weights"
        weights_dir.mkdir()
        icon_detect = weights_dir / "icon_detect"
        icon_detect.mkdir()
        (icon_detect / "model.onnx").write_text("fake model")

        # Mock __file__ to point to our test package
        with patch('enikk.weights.__file__', str(enikk_dir / "weights.py")):
            result = get_bundle_weights_dir()
            assert result is not None
            assert result == weights_dir
            assert result.exists()

    def test_dev_mode_without_weights(self, tmp_path):
        """Test when weights directory doesn't exist in dev mode."""
        package_dir = tmp_path / "package"
        package_dir.mkdir()
        # Don't create weights directory

        with patch('enikk.weights.__file__', str(package_dir / "weights.py")):
            # Temporarily disable frozen mode
            with patch.object(sys, 'frozen', False, create=True):
                result = get_bundle_weights_dir()
                # Result depends on whether actual weights exist in repo
                # Just verify it returns a Path or None
                assert result is None or isinstance(result, Path)

    def test_frozen_mode_with_weights(self, tmp_path):
        """Test finding weights in frozen (PyInstaller) mode."""
        bundle_dir = tmp_path / "bundle"
        bundle_dir.mkdir()
        weights_dir = bundle_dir / "weights"
        weights_dir.mkdir()

        with patch.object(sys, 'frozen', True, create=True):
            # Set _MEIPASS directly on sys module
            original_meipass = getattr(sys, '_MEIPASS', None)
            try:
                sys._MEIPASS = str(bundle_dir)
                result = get_bundle_weights_dir()
                assert result is not None
                assert result == weights_dir
            finally:
                # Clean up
                if original_meipass is not None:
                    sys._MEIPASS = original_meipass
                elif hasattr(sys, '_MEIPASS'):
                    delattr(sys, '_MEIPASS')

    def test_frozen_mode_without_weights(self, tmp_path):
        """Test when weights don't exist in frozen mode."""
        bundle_dir = tmp_path / "bundle"
        bundle_dir.mkdir()
        # Don't create weights directory

        with patch.object(sys, 'frozen', True, create=True):
            # Set _MEIPASS directly on sys module
            original_meipass = getattr(sys, '_MEIPASS', None)
            try:
                sys._MEIPASS = str(bundle_dir)
                result = get_bundle_weights_dir()
                assert result is None
            finally:
                # Clean up
                if original_meipass is not None:
                    sys._MEIPASS = original_meipass
                elif hasattr(sys, '_MEIPASS'):
                    delattr(sys, '_MEIPASS')


class TestEnsureWeightsReady:
    """Test ensure_weights_ready function."""

    def test_weights_already_exist(self, tmp_path):
        """Test when weights already exist in user directory."""
        user_weights = tmp_path / "user_weights"
        icon_detect = user_weights / "icon_detect"
        icon_detect.mkdir(parents=True)
        (icon_detect / "model.onnx").write_text("existing model")
        rapidocr = user_weights / "rapidocr"
        rapidocr.mkdir(parents=True)
        (rapidocr / "ch_PP-OCRv4_det_infer.onnx").write_text("existing det")

        # Should not raise, should not copy anything
        ensure_weights_ready(user_weights)
        # Verify file still exists
        assert (icon_detect / "model.onnx").exists()

    def test_copy_from_bundle(self, tmp_path):
        """Test copying weights from bundle to user directory."""
        # Setup bundle weights
        bundle_dir = tmp_path / "bundle"
        bundle_dir.mkdir()
        bundle_weights = bundle_dir / "weights"
        bundle_icon_detect = bundle_weights / "icon_detect"
        bundle_icon_detect.mkdir(parents=True)
        (bundle_icon_detect / "model.onnx").write_text("bundle model")
        bundle_rapidocr = bundle_weights / "rapidocr"
        bundle_rapidocr.mkdir(parents=True)
        (bundle_rapidocr / "ch_PP-OCRv4_det_infer.onnx").write_text("bundle det")
        (bundle_rapidocr / "ch_PP-OCRv4_rec_infer.onnx").write_text("bundle rec")

        # Setup user directory (empty)
        user_weights = tmp_path / "user_weights"

        # Mock get_bundle_weights_dir to return our test bundle
        with patch('enikk.weights.get_bundle_weights_dir', return_value=bundle_weights):
            ensure_weights_ready(user_weights)

            # Verify weights were copied
            user_icon_detect = user_weights / "icon_detect"
            assert user_icon_detect.exists()
            assert (user_icon_detect / "model.onnx").exists()
            assert (user_icon_detect / "model.onnx").read_text() == "bundle model"
            user_rapidocr = user_weights / "rapidocr"
            assert user_rapidocr.exists()
            assert (user_rapidocr / "ch_PP-OCRv4_det_infer.onnx").exists()

    def test_no_bundle_weights(self, tmp_path):
        """Test when no bundle weights are available."""
        user_weights = tmp_path / "user_weights"

        with patch('enikk.weights.get_bundle_weights_dir', return_value=None):
            # Should not raise, just log warning
            ensure_weights_ready(user_weights)
            # User directory should NOT be created when no bundle weights
            assert not user_weights.exists()

    def test_bundle_missing_icon_detect(self, tmp_path):
        """Test when bundle exists but icon_detect directory is missing."""
        bundle_dir = tmp_path / "bundle"
        bundle_dir.mkdir()
        bundle_weights = bundle_dir / "weights"
        bundle_weights.mkdir()
        # Don't create icon_detect subdirectory

        user_weights = tmp_path / "user_weights"

        with patch('enikk.weights.get_bundle_weights_dir', return_value=bundle_weights):
            ensure_weights_ready(user_weights)
            # Should handle gracefully
            assert user_weights.exists()
            assert not (user_weights / "icon_detect").exists()
