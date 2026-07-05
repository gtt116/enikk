"""Screenshot capture by window handle."""
from __future__ import annotations

import logging
import time

import cv2
import mss
import numpy as np

from . import window

logger = logging.getLogger(__name__)


class CaptureService:
    """Stateless screenshot capture for a window client area."""

    def __init__(self, window_service: window.WindowService | None = None):
        self.window = window_service or window.WindowService()

    def capture(self, hwnd: int, *, activate: bool = True) -> np.ndarray | None:
        """Capture a window client area as a BGR image."""
        if not self.window.is_valid(hwnd):
            logger.error("Capture failed: invalid hwnd=%r", hwnd)
            return None

        try:
            # 这里默认窗口是在前台的，所以不操作窗口一定要在前台；因为如果多一步窗口放前台，下拉框操作会截图不全
            if activate:
                self.window.force_foreground(hwnd)

            region = self.window.get_window_region(hwnd)

            if region is None:
                logger.error("Capture failed: hwnd=%d has no client region", hwnd)
                return None

            r = region.as_tuple()
            with mss.mss() as sct:
                raw = sct.grab({"left": r[0], "top": r[1], "width": r[2], "height": r[3]})
            image = np.array(raw)

            return cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
        except Exception as e:
            logger.error("Capture failed for hwnd=%d: %s", hwnd, e, exc_info=True)
            return None

    def save(self, hwnd: int, path: str, *, activate: bool = True) -> bool:
        """Capture and save screenshot to file. Returns True on success."""
        img = self.capture(hwnd, activate=activate)
        if img is None:
            return False
        # 1. 将图像编码为内存字节流，注意第一个参数 '.png' 必须与你想要的保存格式一致
        success, encoded_img = cv2.imencode('.jpeg', img)
        # 2. 如果编码成功，使用 tofile 写入包含中文的路径
        if success:
            encoded_img.tofile(path)
            return True
        else:
            return cv2.imwrite(path, img)
            logger.error("img encoding error, save image by 'cv2.imwrite' directly.")


if __name__ == '__main__':
    import win32gui
    hwnd = win32gui.FindWindow("MSPaintApp", None)
    path="C:\\Users\\luisyu\\Desktop\\11.jpg"
    time.sleep(5)
    print(f"hwnd:{hwnd}")
    CaptureService().save(hwnd,path, activate=True)