"""Optional Interception mouse input backend."""

import ctypes
import os
import sys
import time
from pathlib import Path

import win32gui
import win32con


_LEFT_DOWN = 0x001
_LEFT_UP = 0x002
_MOVE_ABSOLUTE = 0x001
_VIRTUAL_DESKTOP = 0x002
_INSTALL_HINT = (
    "To install the Interception driver, run this from the Enikk directory "
    "in an administrator PowerShell:\n"
    r"& '.\tools\Interception\Interception\command line installer\install-interception.exe' /install"
)


class _MouseStroke(ctypes.Structure):
    _fields_ = [
        ("state", ctypes.c_ushort),
        ("flags", ctypes.c_ushort),
        ("rolling", ctypes.c_short),
        ("x", ctypes.c_int),
        ("y", ctypes.c_int),
        ("information", ctypes.c_uint),
    ]


def _load_dll():
    configured_path = os.environ.get("ENIKK_INTERCEPTION_DLL")
    if configured_path:
        path = Path(configured_path).resolve()
    else:
        enikk_dir = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[2]
        path = enikk_dir / "tools/Interception/Interception/library/x64/interception.dll"
    if not path.is_file():
        raise OSError("Interception DLL not found. Set ENIKK_INTERCEPTION_DLL to its path.")
    dll = ctypes.CDLL(str(path))
    dll.interception_create_context.restype = ctypes.c_void_p
    dll.interception_destroy_context.argtypes = [ctypes.c_void_p]
    dll.interception_destroy_context.restype = None
    dll.interception_send.argtypes = [
        ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(_MouseStroke), ctypes.c_uint,
    ]
    dll.interception_send.restype = ctypes.c_int
    dll.interception_get_hardware_id.argtypes = [
        ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint,
    ]
    dll.interception_get_hardware_id.restype = ctypes.c_uint
    return dll


def _mouse_device(dll, context) -> int:
    first_mouse = None
    # Interception reserves device IDs 1–10 for keyboards.
    for device in range(11, 21):
        buffer = ctypes.create_string_buffer(1024)
        size = dll.interception_get_hardware_id(context, device, buffer, len(buffer))
        if not size:
            continue
        hardware_id = buffer.raw[:size].decode("utf-16-le", errors="ignore").upper()
        if "VID_2717" in hardware_id:
            return device
        if first_mouse is None:
            first_mouse = device
    if first_mouse is None:
        raise OSError(f"Interception could not find a mouse device. {_INSTALL_HINT}")
    return first_mouse


def click(x: int, y: int, *, hwnd: int, clicks: int, duration_ms: int) -> None:
    """Move to a screen pixel and send a timed left-button press."""
    user32 = ctypes.windll.user32
    left, top, width, height = (
        user32.GetSystemMetrics(metric)
        for metric in (
            win32con.SM_XVIRTUALSCREEN,
            win32con.SM_YVIRTUALSCREEN,
            win32con.SM_CXVIRTUALSCREEN,
            win32con.SM_CYVIRTUALSCREEN,
        )
    )
    if not (left <= x < left + width and top <= y < top + height):
        raise OSError("Target point is outside the virtual desktop.")
    abs_x = round((x - left) * 65535 / max(1, width - 1))
    abs_y = round((y - top) * 65535 / max(1, height - 1))

    try:
        dll = _load_dll()
    except (OSError, AttributeError) as exc:
        raise OSError(f"Interception DLL unavailable: {exc}\n{_INSTALL_HINT}") from exc
    context = dll.interception_create_context()
    if not context:
        raise OSError(f"Could not open an Interception context. {_INSTALL_HINT}")
    try:
        device = _mouse_device(dll, context)

        def send(stroke: _MouseStroke) -> None:
            if dll.interception_send(context, device, ctypes.byref(stroke), 1) != 1:
                raise OSError("Interception could not send a mouse event.")

        move_flags = _MOVE_ABSOLUTE | _VIRTUAL_DESKTOP
        send(_MouseStroke(flags=move_flags, x=abs_x, y=abs_y))
        time.sleep(0.06)
        for index in range(clicks):
            if index:
                time.sleep(0.10)
            if win32gui.GetForegroundWindow() != hwnd:
                raise OSError("Target window lost focus before mouse press.")
            # Position and press in the same stroke, even after a click delay.
            send(_MouseStroke(state=_LEFT_DOWN, flags=move_flags, x=abs_x, y=abs_y))
            try:
                time.sleep(duration_ms / 1000)
            finally:
                send(_MouseStroke(state=_LEFT_UP))
    finally:
        dll.interception_destroy_context(context)
