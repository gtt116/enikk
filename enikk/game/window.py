"""Windows window discovery and foreground helpers."""
from __future__ import annotations

import ctypes
import logging
import os
import time

import psutil
import win32gui
import win32process

from .types import Region

# Make this process DPI-aware so all coordinates are physical pixels,
# matching what screen capture libraries (mss, pyautogui) expect.
ctypes.windll.user32.SetProcessDPIAware()

logger = logging.getLogger(__name__)

SW_SHOWNORMAL = 1

_user32 = ctypes.WinDLL("user32")
_kernel32 = ctypes.WinDLL("kernel32")

_kernel32.GetCurrentThreadId.argtypes = []
_kernel32.GetCurrentThreadId.restype = ctypes.c_ulong

_user32.AttachThreadInput.argtypes = [ctypes.c_ulong, ctypes.c_ulong, ctypes.c_bool]
_user32.AttachThreadInput.restype = ctypes.c_bool

_user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
_user32.SetForegroundWindow.restype = ctypes.c_bool

_user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
_user32.ShowWindow.restype = ctypes.c_bool

_user32.SetWindowPos.argtypes = [
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_uint,
]
_user32.SetWindowPos.restype = ctypes.c_bool


def _same_path(left: str, right: str) -> bool:
    return os.path.normcase(os.path.normpath(left)) == os.path.normcase(os.path.normpath(right))


def _area(hwnd: int) -> int:
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    return (right - left) * (bottom - top)


class WindowService:
    """Stateless Win32 window operations."""

    def is_valid(self, hwnd: int | None) -> bool:
        return bool(hwnd and win32gui.IsWindow(hwnd))

    def find_by_path_and_class(self, exe_path: str, window_class: str | None) -> int | None:
        """Find a visible window by executable path and optional class name."""
        hwnds: list[int] = []

        def enum_windows_callback(hwnd, _):
            try:
                if not win32gui.IsWindowVisible(hwnd):
                    return
                if window_class and win32gui.GetClassName(hwnd) != window_class:
                    return

                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                try:
                    proc = psutil.Process(pid)
                    if not _same_path(proc.exe(), exe_path):
                        return
                except (psutil.AccessDenied, psutil.NoSuchProcess):
                    return

                hwnds.append(hwnd)
            except Exception:
                pass

        win32gui.EnumWindows(enum_windows_callback, None)

        if hwnds:
            # Pick the largest window when multiple match (avoids tiny helper windows)
            hwnd = max(hwnds, key=lambda h: _area(h))
            title = win32gui.GetWindowText(hwnd)
            logger.info("Found window hwnd=%d, class=%r, title=%r", hwnd, window_class, title)
            logger.debug("Found %d matching windows: %s", len(hwnds),
                         [(h, win32gui.GetWindowText(h)) for h in hwnds])
            return hwnd

        logger.debug("No window found for class=%r, path=%r", window_class, exe_path)
        return None

    def get_client_region(self, hwnd: int) -> Region | None:
        """Return the client area in screen coordinates."""
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        width = right - left
        height = bottom - top

        client_left, client_top, client_right, client_bottom = win32gui.GetClientRect(hwnd)
        client_width = client_right - client_left
        client_height = client_bottom - client_top

        if client_width <= 0 or client_height <= 0:
            logger.debug("Window has no client area: %dx%d", client_width, client_height)
            return None

        border_width = (width - client_width) // 2
        border_height = height - client_height - border_width
        return Region(
            left=left + border_width,
            top=top + border_height,
            width=client_width,
            height=client_height,
        )

    def force_foreground(self, hwnd: int) -> bool:
        """Force a window to the foreground, bypassing Windows foreground lock."""
        try:
            _user32.ShowWindow(hwnd, SW_SHOWNORMAL)
        except Exception:
            pass

        fg_hwnd = win32gui.GetForegroundWindow()
        if fg_hwnd == hwnd:
            return True

        fg_tid = win32process.GetWindowThreadProcessId(fg_hwnd)[0]
        my_tid = _kernel32.GetCurrentThreadId()

        if fg_tid != my_tid:
            _user32.AttachThreadInput(fg_tid, my_tid, True)

        try:
            _user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002)
            _user32.SetWindowPos(hwnd, -2, 0, 0, 0, 0, 0x0001 | 0x0002)
            _user32.SetForegroundWindow(hwnd)
        finally:
            if fg_tid != my_tid:
                _user32.AttachThreadInput(fg_tid, my_tid, False)

        time.sleep(0.05)
        return win32gui.GetForegroundWindow() == hwnd
