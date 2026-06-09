"""OmniParser-style UI analysis: YOLO icon detection + OCR text recognition."""
import logging
import os
import platform
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import cv2
import numpy as np
import onnxruntime as ort
from rapidocr_onnxruntime import RapidOCR

logger = logging.getLogger(__name__)


def _letterbox(img: np.ndarray, new_shape: tuple[int, int] = (640, 640),
               color: tuple[int, int, int] = (114, 114, 114)) -> tuple[np.ndarray, float, tuple[float, float]]:
    """Resize image with padding to maintain aspect ratio.

    Returns:
        - Resized and padded image
        - Scale ratio
        - Padding (dw, dh)
    """
    shape = img.shape[:2]  # current shape [height, width]
    r = min(new_shape[0] / shape[0], new_shape[1] / shape[1])

    new_unpad = int(round(shape[1] * r)), int(round(shape[0] * r))
    dw = (new_shape[1] - new_unpad[0]) / 2
    dh = (new_shape[0] - new_unpad[1]) / 2

    if shape[::-1] != new_unpad:
        img = cv2.resize(img, new_unpad, interpolation=cv2.INTER_LINEAR)

    top, bottom = int(round(dh - 0.1)), int(round(dh + 0.1))
    left, right = int(round(dw - 0.1)), int(round(dw + 0.1))
    img = cv2.copyMakeBorder(img, top, bottom, left, right, cv2.BORDER_CONSTANT, value=color)

    return img, r, (dw, dh)


def _xywh2xyxy(x: np.ndarray) -> np.ndarray:
    """Convert [x, y, w, h] to [x1, y1, x2, y2]."""
    y = np.copy(x)
    y[..., 0] = x[..., 0] - x[..., 2] / 2
    y[..., 1] = x[..., 1] - x[..., 3] / 2
    y[..., 2] = x[..., 0] + x[..., 2] / 2
    y[..., 3] = x[..., 1] + x[..., 3] / 2
    return y


def _nms(boxes: np.ndarray, scores: np.ndarray, iou_threshold: float = 0.7) -> np.ndarray:
    """Non-Maximum Suppression.

    Args:
        boxes: (N, 4) array of boxes in xyxy format
        scores: (N,) array of confidence scores
        iou_threshold: IoU threshold for suppression

    Returns:
        Array of indices to keep
    """
    if len(boxes) == 0:
        return np.array([], dtype=int)

    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = (x2 - x1) * (y2 - y1)
    order = scores.argsort()[::-1]

    keep = []
    while order.size > 0:
        i = order[0]
        keep.append(i)

        if order.size == 1:
            break

        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])

        w = np.maximum(0.0, xx2 - xx1)
        h = np.maximum(0.0, yy2 - yy1)
        inter = w * h

        iou = inter / (areas[i] + areas[order[1:]] - inter)
        inds = np.where(iou <= iou_threshold)[0]
        order = order[inds + 1]

    return np.array(keep, dtype=int)


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


def _is_dml_safe_for_rapidocr() -> bool:
    """Check if rapidocr_onnxruntime's _check_dml() can parse the Windows version.

    rapidocr_onnxruntime <= 1.4.4 crashes on Windows Server where platform.release()
    returns strings like '2025Server' instead of a numeric version.
    """
    if platform.system() != "Windows":
        return False
    try:
        int(platform.release().split(".")[0])
        return True
    except (ValueError, IndexError):
        return False


class UIParser:
    """Pre-loads YOLO + OCR models, parses compressed screenshots."""

    def __init__(self, weights_dir: str | None = None, screenshot_max_dim: int = 1366,
                 use_dml: bool = False):
        self.max_dim = screenshot_max_dim
        self.yolo_session = None
        self.use_dml = use_dml or "DmlExecutionProvider" in ort.get_available_providers()
        self._inference_lock = threading.Lock() if self.use_dml else None
        if self.use_dml:
            logger.info("DirectML enabled (providers: %s)", ort.get_available_providers())
        else:
            logger.info("DirectML not available, using CPU (providers: %s)", ort.get_available_providers())

        # Build RapidOCR kwargs
        # rapidocr_onnxruntime has a bug parsing Windows Server version strings (e.g. '2025Server'),
        # so we only enable DML for OCR when the Windows version is safely parseable
        ocr_kwargs: dict[str, Any] = {}
        if self.use_dml and _is_dml_safe_for_rapidocr():
            ocr_kwargs["det_use_dml"] = True
            ocr_kwargs["cls_use_dml"] = True
            ocr_kwargs["rec_use_dml"] = True
            logger.info("DirectML enabled for RapidOCR")
        elif self.use_dml:
            logger.warning("DirectML disabled for RapidOCR (unsupported Windows version)")
        if weights_dir:
            rapidocr_dir = os.path.join(weights_dir, "rapidocr")
            det_path = os.path.join(rapidocr_dir, "ch_PP-OCRv4_det_infer.onnx")
            cls_path = os.path.join(rapidocr_dir, "ch_ppocr_mobile_v2.0_cls_infer.onnx")
            rec_path = os.path.join(rapidocr_dir, "ch_PP-OCRv4_rec_infer.onnx")
            if os.path.exists(det_path) and os.path.exists(rec_path):
                ocr_kwargs["det_model_path"] = det_path
                ocr_kwargs["cls_model_path"] = cls_path
                ocr_kwargs["rec_model_path"] = rec_path
                logger.info(f"Using RapidOCR models from: {rapidocr_dir}")
            else:
                logger.warning(f"RapidOCR models not found in {rapidocr_dir}, using bundled defaults")

        self.ocr = RapidOCR(**ocr_kwargs)

        if weights_dir:
            onnx_path = os.path.join(weights_dir, "icon_detect", "model.onnx")
            if not os.path.exists(onnx_path):
                logger.warning(f"ONNX model not found: {onnx_path}. Run: python scripts/export_yolo_onnx.py weights/icon_detect/model.pt")
            else:
                try:
                    providers = ["DmlExecutionProvider", "CPUExecutionProvider"] if self.use_dml else ["CPUExecutionProvider"]
                    logger.info(f"Loading YOLO ONNX: {onnx_path} (providers={providers})")
                    self.yolo_session = ort.InferenceSession(onnx_path, providers=providers)
                    logger.info("YOLO ONNX model loaded")
                except Exception as e:
                    logger.warning(f"Failed to load YOLO ONNX model: {e}", exc_info=True)
                    self.yolo_session = None
        else:
            logger.info("No weights_dir provided, YOLO icon detection disabled")

    def _compress(self, image: np.ndarray) -> tuple[np.ndarray, tuple]:
        """Resize image so max dimension <= self.max_dim, preserving aspect ratio."""
        h, w = image.shape[:2]
        if w <= self.max_dim and h <= self.max_dim:
            return image, (h, w)
        scale = self.max_dim / max(w, h)
        resized = cv2.resize(image, (int(w * scale), int(h * scale)))
        return resized, (h, w)

    def _detect_icons(self, resized: np.ndarray) -> list[dict]:
        """YOLO ONNX detection on compressed image. Returns boxes in normalized [0, 1000]."""
        if self.yolo_session is None:
            return []

        t0 = time.time()
        orig_h, orig_w = resized.shape[:2]

        # Preprocess: letterbox to 640x640, normalize, transpose to BCHW
        img, ratio, (dw, dh) = _letterbox(resized, (640, 640))
        img = img.astype(np.float32) / 255.0
        img = img.transpose(2, 0, 1)[np.newaxis, ...]  # HWC -> BCHW

        # Inference
        input_name = self.yolo_session.get_inputs()[0].name
        if self._inference_lock:
            with self._inference_lock:
                output = self.yolo_session.run(None, {input_name: img})[0]
        else:
            output = self.yolo_session.run(None, {input_name: img})[0]

        # Post-process: transpose (1, 5, 8400) -> (8400, 5)
        output = output[0].transpose(1, 0)  # (8400, 5)
        boxes_xywh = output[:, :4]
        scores = output[:, 4]

        # Confidence threshold
        mask = scores > 0.01
        boxes_xywh = boxes_xywh[mask]
        scores = scores[mask]

        if len(boxes_xywh) == 0:
            return []

        # Convert xywh -> xyxy
        boxes_xyxy = _xywh2xyxy(boxes_xywh)

        # Rescale to original image coordinates
        boxes_xyxy[:, [0, 2]] = (boxes_xyxy[:, [0, 2]] - dw) / ratio
        boxes_xyxy[:, [1, 3]] = (boxes_xyxy[:, [1, 3]] - dh) / ratio

        # Clip to image bounds
        boxes_xyxy[:, [0, 2]] = boxes_xyxy[:, [0, 2]].clip(0, orig_w)
        boxes_xyxy[:, [1, 3]] = boxes_xyxy[:, [1, 3]].clip(0, orig_h)

        # NMS
        keep = _nms(boxes_xyxy, scores, iou_threshold=0.7)
        boxes_xyxy = boxes_xyxy[keep]
        scores = scores[keep]

        # Build result
        raw: list[tuple] = []
        for box, score in zip(boxes_xyxy, scores):
            x1, y1, x2, y2 = box
            raw.append((x1, y1, x2, y2, "icon"))

        # Sort top-to-bottom, left-to-right for stable IDs across frames
        raw.sort(key=lambda b: (int((b[1] + b[3]) / 2), int((b[0] + b[2]) / 2)))

        boxes: list[dict] = []
        for x1, y1, x2, y2, label in raw:
            boxes.append({
                "bbox": [
                    max(0, min(1000, int(x1 / orig_w * 1000))),
                    max(0, min(1000, int(y1 / orig_h * 1000))),
                    max(0, min(1000, int(x2 / orig_w * 1000))),
                    max(0, min(1000, int(y2 / orig_h * 1000))),
                ],
                "label": label,
            })
        logger.info("YOLO: %.0fms, %d icons", (time.time() - t0) * 1000, len(boxes))
        return boxes

    def _detect_text(self, resized: np.ndarray) -> list[dict]:
        """OCR on compressed image. Boxes normalized to [0, 1000]."""
        t0 = time.time()
        h, w = resized.shape[:2]
        if self._inference_lock:
            with self._inference_lock:
                result, _ = self.ocr(resized)
        else:
            result, _ = self.ocr(resized)
        if not result:
            logger.info("OCR: %.0fms, 0 texts", (time.time() - t0) * 1000)
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
        logger.info("OCR: %.0fms, %d texts", (time.time() - t0) * 1000, len(texts))
        return texts

    @staticmethod
    def _remove_overlap(yolo_boxes: list[dict], iou_threshold: float = 0.7,
                        ocr_boxes: list[dict] | None = None) -> list[dict]:
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

    def parse(self, image: np.ndarray) -> list[dict]:
        """Full pipeline: compress → YOLO + OCR (parallel) → overlap removal → normalized output."""
        t0 = time.time()

        compressed, _ = self._compress(image)
        t1 = time.time()

        # DirectML is not thread-safe: run sequentially when DML is active
        if self.use_dml:
            ocr_results = self._detect_text(compressed)
            icon_results = self._detect_icons(compressed)
        else:
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
