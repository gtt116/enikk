"""Unit tests for ui_parser."""
import concurrent.futures
import os
import sys

import cv2
import numpy as np
import pytest

# Allow importing enikk package from parent directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from enikk.ui_parser import UIParser, _box_area, _intersection_area, _iou, _is_inside

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCREENSHOT_PATH = os.path.join(PROJECT_ROOT, "screenshots", "20260509_152323.jpg")


# ── Geometry helpers ──────────────────────────────────────────────────


class TestBoxArea:
    def test_positive_area(self):
        assert _box_area([0, 0, 10, 10]) == 100

    def test_zero_area(self):
        assert _box_area([0, 0, 0, 10]) == 0

    def test_negative_coords(self):
        assert _box_area([-5, -5, 5, 5]) == 100


class TestIntersectionArea:
    def test_no_overlap(self):
        assert _intersection_area([0, 0, 10, 10], [20, 20, 30, 30]) == 0

    def test_full_overlap(self):
        b = [0, 0, 10, 10]
        assert _intersection_area(b, b) == 100

    def test_partial_overlap(self):
        assert _intersection_area([0, 0, 10, 10], [5, 5, 15, 15]) == 25

    def test_one_inside_other(self):
        assert _intersection_area([0, 0, 20, 20], [5, 5, 15, 15]) == 100


class TestIou:
    def test_identical_boxes(self):
        b = [0, 0, 10, 10]
        assert _iou(b, b) == pytest.approx(1.0)

    def test_no_overlap(self):
        assert _iou([0, 0, 10, 10], [20, 20, 30, 30]) == 0

    def test_partial_overlap(self):
        result = _iou([0, 0, 10, 10], [5, 5, 15, 15])
        assert 0 < result < 1


class TestIsInside:
    def test_fully_inside(self):
        assert _is_inside([2, 2, 8, 8], [0, 0, 10, 10]) is True

    def test_not_inside(self):
        assert _is_inside([0, 0, 10, 10], [2, 2, 8, 8]) is False

    def test_partial_inside(self):
        assert _is_inside([0, 0, 10, 10], [5, 5, 15, 15]) is False

    def test_empty_box(self):
        assert _is_inside([0, 0, 0, 0], [0, 0, 10, 10]) is False


# ── _remove_overlap ───────────────────────────────────────────────────


class TestRemoveOverlap:
    def test_no_ocr_returns_yolo_as_is(self):
        yolo = [{"bbox": [100, 100, 200, 200], "label": "icon_a"}]
        result = UIParser._remove_overlap(yolo, ocr_boxes=None)
        assert result == yolo

    def test_ocr_inside_yolo_replaces_text(self):
        yolo = [{"bbox": [100, 100, 300, 300], "label": "icon"}]
        ocr = [{"text": "Confirm", "bbox": [150, 150, 250, 250], "confidence": 0.9}]
        result = UIParser._remove_overlap(yolo, ocr_boxes=ocr)
        assert len(result) == 1
        assert result[0]["text"] == "Confirm"
        assert result[0]["bbox"] == [100, 100, 300, 300]

    def test_yolo_inside_ocr_skipped(self):
        yolo = [{"bbox": [150, 150, 250, 250], "label": "icon"}]
        ocr = [{"text": "Button", "bbox": [100, 100, 300, 300], "confidence": 0.8}]
        result = UIParser._remove_overlap(yolo, ocr_boxes=ocr)
        assert len(result) == 1
        assert result[0]["text"] == "Button"

    def test_dominant_yolo_skipped(self):
        """Larger box that overlaps smaller one should be skipped."""
        small = {"bbox": [150, 150, 250, 250], "label": "small"}
        large = {"bbox": [100, 100, 300, 300], "label": "large"}
        result = UIParser._remove_overlap([small, large], ocr_boxes=None)
        labels = [b.get("label") for b in result]
        assert "large" not in labels

    def test_non_overlapping_both_kept(self):
        yolo = [
            {"bbox": [0, 0, 100, 100], "label": "a"},
            {"bbox": [500, 500, 600, 600], "label": "b"},
        ]
        result = UIParser._remove_overlap(yolo, ocr_boxes=None)
        assert len(result) == 2


# ── UIParser end-to-end ──────────────────────────────────────────────


class TestUIParser:
    def _get_parser(self):
        """Create UIParser without YOLO (weights may not be available)."""
        return UIParser(weights_dir=None)

    def _load_screenshot(self):
        if not os.path.exists(SCREENSHOT_PATH):
            pytest.skip(f"Screenshot not found: {SCREENSHOT_PATH}")
        img = cv2.imread(SCREENSHOT_PATH)
        assert img is not None, "Failed to load screenshot"
        return img

    def test_parse_returns_list(self):
        parser = self._get_parser()
        img = self._load_screenshot()
        result = parser.parse(img)
        assert isinstance(result, list)

    def test_parse_boxes_have_valid_coords(self):
        parser = self._get_parser()
        img = self._load_screenshot()
        result = parser.parse(img)
        for item in result:
            if "bbox" in item:
                b = item["bbox"]
                assert len(b) == 4
                assert all(0 <= v <= 1000 for v in b)
            if "bbox" in item:
                b = item["bbox"]
                assert len(b) == 4
                assert all(0 <= v <= 1000 for v in b)

    def test_parse_ocr_items_have_text(self):
        parser = self._get_parser()
        img = self._load_screenshot()
        result = parser.parse(img)
        print(result)
        ocr_items = [i for i in result if "text" in i]
        for item in ocr_items:
            assert isinstance(item["text"], str)
            assert len(item["text"]) > 0

    def test_parse_image_compression_does_not_crash(self):
        """Verify that various image sizes are handled."""
        parser = self._get_parser()
        # Create a synthetic image
        img = np.random.randint(0, 255, (1080, 1920, 3), dtype=np.uint8)
        result = parser.parse(img)
        assert isinstance(result, list)

    def test_parse_empty_image(self):
        """Black image should still return without errors."""
        parser = self._get_parser()
        img = np.zeros((768, 1366, 3), dtype=np.uint8)
        result = parser.parse(img)
        assert isinstance(result, list)

    def test_parse_items_have_center(self):
        """Every item in parse() output should have a center coordinate."""
        parser = self._get_parser()
        img = np.zeros((768, 1366, 3), dtype=np.uint8)
        result = parser.parse(img)
        for item in result:
            if "bbox" in item:
                assert "center" in item
                c = item["center"]
                b = item["bbox"]
                assert len(c) == 2
                assert c[0] == (b[0] + b[2]) // 2
                assert c[1] == (b[1] + b[3]) // 2

    def test_parse_deterministic(self):
        """Multiple calls with the same image should produce the same result (parallel safety)."""
        parser = self._get_parser()
        img = np.random.randint(0, 255, (768, 1366, 3), dtype=np.uint8)
        result1 = parser.parse(img)
        result2 = parser.parse(img)
        # Same number of items (parallel order is deterministic: OCR always first in merged list)
        assert len(result1) == len(result2)
        for a, b in zip(result1, result2):
            assert a.get("bbox") == b.get("bbox")
            assert a.get("text") == b.get("text")

    def test_parse_parallel_runs(self):
        """Verify parse() completes without race conditions (smoke test for ThreadPoolExecutor)."""
        parser = self._get_parser()
        # Run multiple parses concurrently to stress-test thread safety
        imgs = [np.random.randint(0, 255, (768, 1366, 3), dtype=np.uint8) for _ in range(5)]

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(parser.parse, img) for img in imgs]
            results = [f.result(timeout=30) for f in futures]

        for r in results:
            assert isinstance(r, list)
