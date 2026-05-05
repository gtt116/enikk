"""Game state analysis via CV + RapidOCR."""
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
from rapidocr_onnxruntime import RapidOCR

logger = logging.getLogger("enikk")


@dataclass
class GameState:
    game_state: str = "unknown"
    state_reason: str = ""
    actions: list = field(default_factory=list)
    ocr_text: list = field(default_factory=list)
    template_matches: dict = field(default_factory=dict)
    timestamp: str = ""
    analysis_time_ms: float = 0.0
    resolution: str = ""


class GameAnalyzer:
    """Analyzes game screenshots to determine state."""

    def __init__(self, assets_dir: str = None):
        self.assets_dir = Path(assets_dir) if assets_dir else Path(__file__).parent.parent / "assets"
        self.ocr = None
        self._templates = {}

    def _ensure_ocr(self):
        """Lazy init RapidOCR."""
        if self.ocr is None:
            logger.info("Initializing RapidOCR...")
            self.ocr = RapidOCR(use_angle_cls=False)
            logger.info("RapidOCR ready")

    def _detect_loading(self, image: np.ndarray) -> bool:
        """Detect loading screen via bright histogram."""
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        hist = cv2.calcHist([gray], [0], None, [256], [0, 256])
        total = gray.shape[0] * gray.shape[1]
        bright_ratio = hist[200:].sum() / total
        return bright_ratio > 0.5

    def _detect_lobby(self, image: np.ndarray) -> bool:
        """Detect lobby via white peak (UI elements)."""
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        hist = cv2.calcHist([gray], [0], None, [256], [0, 256])
        total = gray.shape[0] * gray.shape[1]
        white_ratio = hist[240:].sum() / total
        return 0.05 < white_ratio < 0.3

    def _ocr_extract(self, image: np.ndarray) -> list[dict]:
        """Extract text via RapidOCR."""
        self._ensure_ocr()
        result, _ = self.ocr(image)
        if not result:
            return []

        texts = []
        for item in result:
            box, text, conf = item[0], item[1], item[2]
            texts.append({"text": text, "box": box, "confidence": conf})
        return texts

    def analyze(self, image: np.ndarray) -> GameState:
        """Analyze screenshot and return game state."""
        start = time.time()
        state = GameState()
        h, w = image.shape[:2]
        state.resolution = f"{w}x{h}"
        state.timestamp = time.strftime("%Y-%m-%dT%H:%M:%S")

        # Detect loading screen
        if self._detect_loading(image):
            state.game_state = "loading"
            state.state_reason = "bright_histogram"
            state.actions = ["wait"]
            state.analysis_time_ms = (time.time() - start) * 1000
            return state

        # OCR analysis
        ocr_results = self._ocr_extract(image)
        state.ocr_text = ocr_results
        all_text = " ".join(r["text"] for r in ocr_results)

        # Determine game state from OCR
        if any(kw in all_text for kw in ["确认", "确定", "OK", "Confirm"]):
            state.game_state = "popup"
            state.state_reason = "detected_ocr_text:确认/确定"
            state.actions = ["action_confirm"]
        elif any(kw in all_text for kw in ["启动", "Launch", "开始游戏"]):
            state.game_state = "launcher"
            state.state_reason = "detected_ocr_text:启动/Launch"
            state.actions = ["action_click_launcher"]
        elif any(kw in all_text for kw in ["登录", "Login", "邮箱", "Email"]):
            state.game_state = "login_screen"
            state.state_reason = "detected_ocr_text:登录/Login"
            state.actions = ["action_login"]
        elif self._detect_lobby(image):
            state.game_state = "lobby"
            state.state_reason = "white_peak_detection+no_loading"
            state.actions = ["idle"]
        else:
            state.game_state = "unknown"
            state.state_reason = "no_template_no_ocr_text"
            state.actions = ["wait"]

        state.analysis_time_ms = (time.time() - start) * 1000
        return state
