"""OmniParser-style UI analysis: YOLO icon detection + OCR text recognition."""
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np
from rapidocr_onnxruntime import RapidOCR
from ultralytics import YOLO

logger = logging.getLogger("enikk")

MAX_DIM = 1366


def _box_area(box):
    return (box[2] - box[0]) * (box[3] - box[1])


def _intersection_area(box1, box2):
    x1 = max(box1[0], box2[0])
    y1 = max(box1[1], box2[1])
    x2 = min(box1[2], box2[2])
    y2 = min(box1[3], box2[3])
    return max(0, x2 - x1) * max(0, y2 - y1)


def _iou(box1, box2):
    inter = _intersection_area(box1, box2)
    union = _box_area(box1) + _box_area(box2) - inter + 1e-6
    r1 = inter / _box_area(box1) if _box_area(box1) > 0 else 0
    r2 = inter / _box_area(box2) if _box_area(box2) > 0 else 0
    return max(inter / union, r1, r2)


def _is_inside(box1, box2):
    """box1 80%+ inside box2."""
    inter = _intersection_area(box1, box2)
    return inter / _box_area(box1) > 0.80 if _box_area(box1) > 0 else False


class UIParser:
    """Pre-loads YOLO + OCR models, parses compressed screenshots."""

    def __init__(self, weights_dir: str = None):
        self.max_dim = MAX_DIM
        self.ocr = RapidOCR(use_angle_cls=False)
        self.yolo: YOLO | None = None

        if weights_dir:
            model_path = os.path.join(weights_dir, "icon_detect", "model.pt")
            try:
                logger.info(f"Loading YOLO: {model_path}")
                self.yolo = YOLO(model_path)
                logger.info("YOLO model loaded")
            except Exception as e:
                logger.warning(f"Failed to load YOLO model: {e}", exc_info=True)
                self.yolo = None
        else:
            logger.info("No weights_dir provided, YOLO icon detection disabled")

    def _compress(self, image: np.ndarray) -> tuple[np.ndarray, tuple]:
        """Resize image so max dimension <= MAX_DIM, preserving aspect ratio. Returns (resized, (orig_h, orig_w))."""
        h, w = image.shape[:2]
        if w <= self.max_dim and h <= self.max_dim:
            return image, (h, w)
        scale = self.max_dim / max(w, h)
        resized = cv2.resize(image, (int(w * scale), int(h * scale)))
        return resized, (h, w)

    def _detect_icons(self, resized: np.ndarray) -> list[dict]:
        """YOLO detection on compressed image. Returns boxes in normalized [0, 1000]."""
        if self.yolo is None:
            return []
        rh, rw = resized.shape[:2]
        results = self.yolo.predict(source=resized, conf=0.01, iou=0.7, verbose=False)
        boxes = []
        for box in results[0].boxes:
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            boxes.append({
                "bbox": [
                    max(0, min(1000, int(x1 / rw * 1000))),
                    max(0, min(1000, int(y1 / rh * 1000))),
                    max(0, min(1000, int(x2 / rw * 1000))),
                    max(0, min(1000, int(y2 / rh * 1000))),
                ],
                "label": "ui_element",
            })
        return boxes

    def _detect_text(self, resized: np.ndarray) -> list[dict]:
        """OCR on compressed image. Boxes normalized to [0, 1000]."""
        h, w = resized.shape[:2]
        result, _ = self.ocr(resized)
        if not result:
            return []
        texts = []
        for item in result:
            box, text, conf = item[0], item[1], item[2]
            xs = [min(p[0] for p in box) / w * 1000, max(p[0] for p in box) / w * 1000]
            ys = [min(p[1] for p in box) / h * 1000, max(p[1] for p in box) / h * 1000]
            texts.append({
                "text": text,
                "bbox": [
                    max(0, int(xs[0])),
                    max(0, int(ys[0])),
                    min(1000, int(xs[1])),
                    min(1000, int(ys[1])),
                ],
                "confidence": round(conf, 3),
            })
        return texts

    @staticmethod
    def _remove_overlap(yolo_boxes: list[dict], iou_threshold: float = 0.7,
                        ocr_boxes: list[dict] = None) -> list[dict]:
        """
        Merge YOLO + OCR boxes, prefer OCR text over YOLO labels.
        - OCR text inside YOLO icon → replace YOLO content with OCR text, remove OCR box
        - YOLO icon inside OCR text → skip YOLO icon
        - Overlapping YOLO boxes → keep smaller one
        """
        filtered = []
        if ocr_boxes:
            filtered.extend(ocr_boxes)

        for i, box1 in enumerate(yolo_boxes):
            b1 = box1["bbox"]
            # YOLO-YOLO dedup: skip if larger box overlaps smaller one
            is_dominated = False
            for j, box2 in enumerate(yolo_boxes):
                if i != j and _iou(b1, box2["bbox"]) > iou_threshold and _box_area(b1) > _box_area(box2["bbox"]):
                    is_dominated = True
                    break
            if is_dominated:
                continue

            # Check against OCR boxes
            if ocr_boxes:
                box_added = False
                ocr_labels = ""
                for ocr_box in ocr_boxes:
                    b3 = ocr_box["bbox"]
                    if _is_inside(b3, b1):
                        ocr_labels += ocr_box["text"] + " "
                        try:
                            filtered.remove(ocr_box)
                        except ValueError:
                            pass
                    elif _is_inside(b1, b3):
                        box_added = True
                        break

                if not box_added:
                    filtered.append({
                        "bbox": b1,
                        "label": box1.get("label", "ui_element"),
                        "text": ocr_labels.strip() if ocr_labels else None,
                    })
            else:
                filtered.append(box1)

        return filtered

    def parse(self, image: np.ndarray) -> dict:
        """Full pipeline: compress → YOLO + OCR (parallel) → overlap removal → normalized output."""
        t0 = time.time()

        compressed, _ = self._compress(image)
        t1 = time.time()

        # Parallel: OCR and YOLO are independent, both read-only on compressed
        with ThreadPoolExecutor(max_workers=2) as executor:
            f_ocr = executor.submit(self._detect_text, compressed)
            f_yolo = executor.submit(self._detect_icons, compressed)
            ocr_results = f_ocr.result()
            icon_results = f_yolo.result()
        t2 = time.time()

        merged = self._remove_overlap(icon_results, iou_threshold=0.7, ocr_boxes=ocr_results)
        for item in merged:
            x1, y1, x2, y2 = item["bbox"]
            item["center"] = [(x1 + x2) // 2, (y1 + y2) // 2]
        t3 = time.time()

        logger.info(
            "UI parse: %.0fms total (compress=%.0fms parallel=%.0fms merge=%.0fms, items=%d)",
            (t3 - t0) * 1000,
            (t1 - t0) * 1000,
            (t2 - t1) * 1000,
            (t3 - t2) * 1000,
            len(merged),
        )

        return merged
