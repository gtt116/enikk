"""OCR-based auto-login for NIKKE launcher."""
import ctypes
import logging
import time

from enum import Enum

from rapidocr_onnxruntime import RapidOCR
from .input import Input

logger = logging.getLogger("enikk")


class LauncherText(str, Enum):
    """Text patterns to detect on launcher."""
    EMAIL = "邮箱"
    PASSWORD = "密码"
    LAUNCH = "启动"
    UPDATE = "更新"
    LOGIN = "登录"
    KEEP_LOGGED_IN = "保持登录"
    FORGET_PASSWORD = "忘记密码"
    ANNOUNCEMENT = "公告"
    INCORRECT_ACCOUNT = "账号格式错误"
    INCORRECT_PASSWORD = "密码错误"
    GAME_SETTING = "游戏设置"


class LauncherLogin:
    """Handle NIKKE launcher login flow via OCR."""

    def __init__(self, capture, input_device: Input):
        self.capture = capture
        self.input = input_device
        self.ocr = RapidOCR(use_angle_cls=False)
        self._ocr_cache = None
        self._cache_time = 0

    def _capture_and_ocr(self, force: bool = False) -> dict | None:
        """Capture screenshot and run OCR, with 2s cache."""
        now = time.time()
        if not force and self._ocr_cache and (now - self._cache_time) < 2:
            logger.debug("Using cached OCR result")
            return self._ocr_cache

        frame = self.capture.capture()
        if frame is None:
            logger.debug("Capture returned None")
            return None

        h, w = frame.shape[:2]
        logger.debug(f"Captured frame {w}x{h}")

        result, _ = self.ocr(frame)
        if not result:
            logger.debug("OCR returned no text")
            return None

        texts = []
        for item in result:
            box, text, conf = item[0], item[1], item[2]
            texts.append({"text": text, "box": box, "confidence": conf})

        all_text = " ".join(t["text"] for t in texts)
        logger.info(f"OCR found {len(texts)} items: {all_text}")
        self._ocr_cache = {"details": texts, "all_text": all_text}
        self._cache_time = now
        return self._ocr_cache

    def appear_text(self, keyword: str, threshold: float = 0.8) -> bool:
        """Check if text appears on screen."""
        data = self._capture_and_ocr()
        if not data:
            return False
        found = any(keyword.lower() in item["text"].lower() for item in data["details"])
        logger.debug(f"appear_text('{keyword}'): {'found' if found else 'not found'}")
        return found

    def get_relative_location(self, keyword: str, data: dict = None) -> tuple[int, int] | None:
        """Get center coordinates of text on screen."""
        if data is None:
            data = self._capture_and_ocr()
        if not data:
            return None
        for item in data["details"]:
            if keyword.lower() in item["text"].lower():
                box = item["box"]
                xs = [p[0] for p in box]
                ys = [p[1] for p in box]
                return (sum(xs) // len(xs), sum(ys) // len(ys))
        return None

    def click_text(self, keyword: str, threshold: float = 0.8) -> bool:
        """Click on text if found, converting relative coords to absolute screen coords."""
        loc = self.get_relative_location(keyword)
        if loc:
            region = self.capture.get_region()
            if region:
                screen_loc = (loc[0] + region[0], loc[1] + region[1])
                logger.info(f"click '{keyword}': region={region}, rel={loc}, abs={screen_loc}")
            else:
                screen_loc = loc
                logger.info(f"click '{keyword}': no region offset, pos={loc}")
            self.input.mouse_click(*screen_loc)
            time.sleep(0.3)
            return True
        logger.info(f"click_text('{keyword}'): not found on screen")
        return False

    def _check_extra_fields(self, data: dict, start: str, end: str) -> tuple:
        """
        Check if there's exactly one extra field between start and end keywords.
        Returns (extra_field_location, extra_field_area) or (None, None).
        """
        if not data:
            return None, None

        # Sort items by Y coordinate
        items = sorted(data["details"], key=lambda x: x["box"][0][1] if x["box"] else 0)

        start_idx = None
        end_idx = None
        for i, item in enumerate(items):
            if start.lower() in item["text"].lower():
                start_idx = i
            if end.lower() in item["text"].lower():
                end_idx = i

        if start_idx is None or end_idx is None:
            return None, None

        # Check items between start and end
        between = items[start_idx + 1: end_idx]
        if len(between) == 1:
            item = between[0]
            box = item["box"]
            if box:
                xs = [p[0] for p in box]
                ys = [p[1] for p in box]
                return (
                    (sum(xs) // len(xs), sum(ys) // len(ys)),
                    [min(xs), min(ys), max(xs), max(ys)]
                )
        return None, None

    def _auto_type(self, text: str):
        """Type text character by character, ensuring English input mode."""
        self._switch_to_english()
        for char in text:
            # Use pyautogui for character input
            self.input.press_key(char, wait_time=0.05)
            time.sleep(0.05)
        time.sleep(0.5)

    def _switch_to_english(self):
        """Switch IME to English if currently Chinese."""
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        thread_id = user32.GetWindowThreadProcessId(hwnd, 0)
        klid = user32.GetKeyboardLayout(thread_id)
        lang_id = klid & 0xFFFF

        # 0x0804 = Simplified Chinese, 0x0404 = Traditional Chinese
        if lang_id in (0x0804, 0x0404):
            logger.info("Switching IME to English")
            self.input.press_key("shift")
            time.sleep(0.2)

    def _close_announcement(self):
        """Close announcement popup if present."""
        if self.appear_text(LauncherText.ANNOUNCEMENT.value):
            logger.info("Closing announcement popup")
            time.sleep(0.3)
            data = self._capture_and_ocr(force=True)
            if data:
                # Find 'X' close button near announcement title
                for i, item in enumerate(data["details"]):
                    if item["text"].strip() == "X":
                        if i > 0:
                            prev = data["details"][i - 1]["text"]
                            if LauncherText.ANNOUNCEMENT.value in prev:
                                loc = self.get_relative_location("X", data)
                                if loc:
                                    self.input.mouse_click(*loc)
                                    time.sleep(0.3)
                                    logger.info("Announcement closed")
                                    break

    def _wait_for_launcher_ready(self, stop_event=None) -> bool:
        """Wait for launcher screen to appear, then click Login if present.
        Returns True if launcher is ready, False if timeout or interrupted.
        """
        max_wait = 60  # seconds
        start = time.time()

        def _sleep(sec):
            if stop_event:
                stop_event.wait(timeout=sec)
                return not stop_event.is_set()
            time.sleep(sec)
            return True

        while time.time() - start < max_wait:
            elapsed = int(time.time() - start)
            if not _sleep(2):
                logger.info(f"Launcher ready timeout ({elapsed}s): interrupted by stop signal")
                return False
            data = self._capture_and_ocr(force=True)
            if not data:
                logger.info(f"Launcher ready timeout ({elapsed}s): capture failed, retrying...")
                continue

            all_text = data["all_text"]
            logger.debug(f"Wait for launcher ({elapsed}s): checking for Launch/Update/email in: {all_text}")
            if LauncherText.LAUNCH.value.lower() in all_text.lower() or \
               LauncherText.UPDATE.value.lower() in all_text.lower():
                logger.info(f"Wait for launcher ({elapsed}s): Launcher ready (Launch/Update button found)")
                break

            if LauncherText.EMAIL.value.lower() in all_text.lower():
                logger.info(f"Wait for launcher ({elapsed}s): Login screen detected (email field found)")
                break
        else:
            logger.error(f"Launcher ready timeout after {int(time.time() - start)}s")
            return False

        # Click Launch/Update
        if self.click_text(LauncherText.LAUNCH.value):
            logger.info("Clicked Launch")
        elif self.click_text(LauncherText.UPDATE.value):
            logger.info("Clicked Update")

        return True

    def login(self, stop_event=None) -> bool:
        """
        Full login flow via launcher OCR.

        Args:
            stop_event: threading.Event for early termination.
        Returns:
            True if login successful, False otherwise.
        """
        logger.info("Starting launcher login flow...")

        def _sleep(sec):
            """Sleep that can be interrupted by stop_event."""
            if stop_event:
                stop_event.wait(timeout=sec)
                return not stop_event.is_set()
            time.sleep(sec)
            return True

        if not self._wait_for_launcher_ready(stop_event):
            return False

        # Phase 4: Wait for game to launch
        logger.info("Waiting for game to start...")
        wait_start = time.time()
        while time.time() - wait_start < 120:
            elapsed = int(time.time() - wait_start)
            if not _sleep(3):
                logger.info(f"Phase 4 ({elapsed}s): interrupted by stop signal")
                return False
            data = self._capture_and_ocr(force=True)
            if not data:
                logger.debug(f"Phase 4 ({elapsed}s): capture failed, retrying...")
                continue

            all_text = data["all_text"]
            logger.debug(f"Phase 4 ({elapsed}s): {all_text}")
            if LauncherText.INCORRECT_ACCOUNT.value in all_text:
                logger.error("Invalid account format")
                return False
            if LauncherText.INCORRECT_PASSWORD.value in all_text:
                logger.error("Incorrect password")
                return False

            if LauncherText.GAME_SETTING.value in all_text or \
               LauncherText.LAUNCH.value in all_text:
                logger.info(f"Phase 4 ({elapsed}s): Login successful, launcher ready to launch game")
                return True
        else:
            logger.error(f"Login timeout after {int(time.time() - wait_start)}s")
            return False
