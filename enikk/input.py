"""Input helpers — foreground input via pyautogui/pynput."""
import time

import numpy as np
import pyautogui
from pynput.mouse import Button, Controller


class Input:
    """Mouse and keyboard input — foreground operation."""

    def __init__(self):
        self.mouse = Controller()

    def mouse_click(self, x, y):
        """Click at screen coordinates."""
        pyautogui.click(x, y)

    def mouse_down(self, x, y):
        """Press mouse button at coordinates."""
        pyautogui.mouseDown(x, y)

    def mouse_up(self):
        """Release mouse button."""
        pyautogui.mouseUp()

    def mouse_move(self, x, y):
        """Move cursor to coordinates."""
        pyautogui.moveTo(x, y)

    def mouse_scroll(self, count, direction=-1):
        """Scroll mouse wheel."""
        for _ in range(count):
            pyautogui.scroll(direction, _pause=True)

    def press_key(self, key, wait_time=0.2):
        """Press and release a key."""
        pyautogui.keyDown(key)
        time.sleep(wait_time)
        pyautogui.keyUp(key)

    def mouse_swipe(self, p1, p2, speed=1.0):
        """Natural swipe using pynput with Bézier curve."""
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
