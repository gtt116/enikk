"""Regression tests for the Interception mouse backend."""

from unittest.mock import Mock, call, patch

import pytest

from enikk.game import interception


@pytest.mark.parametrize("mouse_id", [11, 20])
def test_mouse_device_excludes_keyboard_and_includes_last_mouse(mouse_id):
    dll = Mock()

    def get_hardware_id(_context, device, buffer, _size):
        hardware_id = {10: "keyboard", mouse_id: "mouse"}.get(device, "")
        encoded = hardware_id.encode("utf-16-le")
        buffer[:len(encoded)] = encoded
        return len(encoded)

    dll.interception_get_hardware_id.side_effect = get_hardware_id

    assert interception._mouse_device(dll, 42) == mouse_id
    assert all(11 <= args.args[1] <= 20 for args in dll.interception_get_hardware_id.call_args_list)


def test_each_press_carries_absolute_position():
    dll = Mock()
    dll.interception_create_context.return_value = 42
    dll.interception_send.return_value = 1
    with (
        patch.object(interception, "_load_dll", return_value=dll),
        patch.object(interception, "_mouse_device", return_value=11),
        patch.object(interception.ctypes.windll.user32, "GetSystemMetrics", side_effect=[-100, 0, 101, 101]),
        patch.object(interception.win32gui, "GetForegroundWindow", return_value=123),
        patch.object(interception, "time") as clock,
    ):
        interception.click(-50, 100, hwnd=123, clicks=2, duration_ms=250)

    strokes = [event.args[2]._obj for event in dll.interception_send.call_args_list]
    assert [(stroke.state, stroke.flags, stroke.x, stroke.y) for stroke in strokes] == [
        (0, 3, 32768, 65535),
        (1, 3, 32768, 65535),
        (2, 0, 0, 0),
        (1, 3, 32768, 65535),
        (2, 0, 0, 0),
    ]
    assert clock.sleep.call_args_list == [call(0.06), call(0.25), call(0.10), call(0.25)]
    dll.interception_destroy_context.assert_called_once_with(42)
