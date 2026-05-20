"""Input helpers operating on explicit window handles."""
from __future__ import annotations

import time

import numpy as np
import pyautogui
from pynput.mouse import Button, Controller

from . import window


class InputService:
    """Stateless mouse and keyboard input service."""

    def __init__(self, window_service: window.WindowService | None = None):
        self.window = window_service or window.WindowService()
        self.mouse = Controller()

    def click_screen(self, x: int, y: int) -> dict:
        """Click at absolute screen coordinates."""
        pyautogui.click(x, y, duration=0.6)
        return {"success": True, "x": x, "y": y}

    def click_window(self, hwnd: int, x: int, y: int, *, activate: bool = True) -> dict:
        """Click at client-area coordinates relative to a window."""
        region = self.window.get_client_region(hwnd)
        if region is None:
            return {"success": False, "error": "Window client region not available"}

        abs_x = region.left + x
        abs_y = region.top + y
        if activate:
            self.window.force_foreground(hwnd)
            time.sleep(0.2)
        return self.click_screen(abs_x, abs_y)

    def click_normalized(self, hwnd: int, x: int, y: int, *, activate: bool = True) -> dict:
        """Click at normalized [0, 1000] coordinates within a window client area."""
        if not self.window.is_valid(hwnd):
            return {"success": False, "error": "Invalid window handle"}

        region = self.window.get_client_region(hwnd)
        if region is None:
            return {"success": False, "error": "Window client region not available"}

        abs_x = region.left + int(x / 1000 * region.width)
        abs_y = region.top + int(y / 1000 * region.height)
        if activate:
            self.window.force_foreground(hwnd)
            time.sleep(0.2)
        return self.click_screen(abs_x, abs_y)

    def mouse_down_window(self, hwnd: int, x: int, y: int, *, activate: bool = True) -> dict:
        """Press mouse button at client-area coordinates."""
        region = self.window.get_client_region(hwnd)
        if region is None:
            return {"success": False, "error": "Window client region not available"}

        if activate:
            self.window.force_foreground(hwnd)
            time.sleep(0.2)
        pyautogui.mouseDown(region.left + x, region.top + y)
        return {"success": True, "x": region.left + x, "y": region.top + y}

    def mouse_up(self):
        pyautogui.mouseUp()

    def mouse_move_screen(self, x: int, y: int):
        pyautogui.moveTo(x, y)

    def mouse_scroll(self, count: int, direction: int = -1):
        for _ in range(count):
            pyautogui.scroll(direction, _pause=True)

    def press_key(self, key: str, wait_time: float = 0.2):
        pyautogui.keyDown(key)
        time.sleep(wait_time)
        pyautogui.keyUp(key)

    def swipe_screen(self, p1, p2, speed: float = 1.0):
        """Natural swipe using pynput with linear interpolation."""
        distance = np.linalg.norm(np.array(p2) - np.array(p1))
        segments = max(int(distance / 20), 5)
        total_time = max(0.05, min(distance / (100 * speed), 0.15))
        step_delay = total_time / segments

        self.mouse.position = (p1[0], p1[1])
        time.sleep(0.01)
        self.mouse.press(Button.left)

        for i in range(1, segments + 1):
            t = i / segments
            x = p1[0] + (p2[0] - p1[0]) * t
            y = p1[1] + (p2[1] - p1[1]) * t
            self.mouse.position = (x, y)
            time.sleep(step_delay)

        self.mouse.release(Button.left)


Input = InputService
