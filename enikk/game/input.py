"""Input helpers operating on explicit window handles."""
from __future__ import annotations

import math
import random
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

    def press_key(self, key: str, wait_time: float = 0.2):
        pyautogui.keyDown(key)
        time.sleep(wait_time)
        pyautogui.keyUp(key)

    def swipe_screen(self, p1, p2, speed: float = 1.0):
        """Natural swipe using cubic Bezier curve with easing and random jitter."""
        p1 = np.array(p1, dtype=float)
        p2 = np.array(p2, dtype=float)
        distance = float(np.linalg.norm(p2 - p1))

        # Generate slightly curved path via cubic Bezier with random control points
        offset = distance * 0.2
        perp = np.array([-(p2[1] - p1[1]), p2[0] - p1[0]])
        perp_len = np.linalg.norm(perp)
        if perp_len > 0:
            perp = perp / perp_len
        cp1 = p1 + (p2 - p1) * random.uniform(0.2, 0.4) + perp * random.uniform(-offset, offset)
        cp2 = p1 + (p2 - p1) * random.uniform(0.6, 0.8) + perp * random.uniform(-offset, offset)

        # Number of segments scales with distance
        segments = max(int(distance / 15), 8)
        # Base time with speed factor, capped
        base_time = distance / (200 * speed)
        total_time = random.uniform(max(0.08, base_time * 0.8), base_time * 1.2)

        self.mouse.position = (int(p1[0]), int(p1[1]))
        time.sleep(random.uniform(0.01, 0.03))
        self.mouse.press(Button.left)

        for i in range(1, segments + 1):
            # Ease-in-out: slow at start/end, faster in middle
            t = i / segments
            eased = t * t * (3 - 2 * t)

            # Cubic Bezier interpolation
            b = (1 - eased)**3 * p1 + \
                3 * (1 - eased)**2 * eased * cp1 + \
                3 * (1 - eased) * eased**2 * cp2 + \
                eased**3 * p2

            # Add small random jitter (±1-2 pixels)
            jitter = np.array([random.uniform(-1.5, 1.5), random.uniform(-1.5, 1.5)])
            pos = b + jitter

            self.mouse.position = (int(pos[0]), int(pos[1]))

            # Variable delay: longer at start/end, shorter in middle
            delay_factor = 1.0 + 0.5 * (1 - math.sin(math.pi * eased))
            step_delay = (total_time / segments) * delay_factor
            time.sleep(max(0.001, step_delay))

        self.mouse.release(Button.left)


Input = InputService
