"""Window picker — enumerate and preview visible windows."""
from __future__ import annotations

import logging
import os
import threading

import psutil
import win32gui
import win32process

logger = logging.getLogger(__name__)

# System window class names to exclude
_SYSTEM_CLASSES = frozenset({
    "Progman",           # Desktop
    "Shell_TrayWnd",     # Taskbar
    "WorkerW",           # Desktop worker
    "Shell_SecondaryTrayWnd",
    "TopLevelWindowForOverflowX",
    "NotifyIconOverflowWindow",
})


# Processes that host other apps' windows (UWP frame host, etc.)
_HOST_PROCESSES = frozenset({
    "applicationframehost.exe",
    "explorer.exe",
})

# Processes to exclude from window picking (overlays, system tools)
_EXCLUDED_PROCESSES = frozenset({
    "nvcontainer.exe",           # NVIDIA container
    "nvidia share.exe",          # NVIDIA Share overlay
})

# Window title patterns to exclude (case-insensitive)
_EXCLUDED_TITLE_PATTERNS = (
    "nvidia geforce overlay",
)


def _get_process_name(pid: int) -> str:
    """Get executable name for a PID."""
    try:
        return psutil.Process(pid).name()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return ""


def _get_process_exe(pid: int) -> str:
    """Get full executable path for a PID."""
    try:
        return psutil.Process(pid).exe()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return ""


def _get_window_class(hwnd: int) -> str:
    """Get window class name."""
    try:
        return win32gui.GetClassName(hwnd)
    except Exception:
        return ""


def _resolve_real_pid(hwnd: int, pid: int) -> int:
    """For UWP/hosted windows, find the real app PID from child windows."""
    try:
        exe_name = _get_process_name(pid).lower()
    except Exception:
        return pid
    if exe_name not in _HOST_PROCESSES:
        return pid

    real_pid = pid

    def enum_child(child_hwnd, _):
        nonlocal real_pid
        try:
            _, child_pid = win32process.GetWindowThreadProcessId(child_hwnd)
            if child_pid != pid and child_pid != os.getpid():
                real_pid = child_pid
        except Exception:
            pass
        return True

    try:
        win32gui.EnumChildWindows(hwnd, enum_child, None)
    except Exception:
        pass
    return real_pid


class WindowPicker:
    """Enumerate visible windows and generate previews."""

    def __init__(self):
        self._own_pid = os.getpid()

    def enum_visible_windows(self) -> list[dict]:
        """Return all user-visible, non-system windows."""
        windows: list[dict] = []

        def callback(hwnd: int, _) -> bool:
            try:
                if not win32gui.IsWindowVisible(hwnd):
                    return True
                if win32gui.IsIconic(hwnd):
                    return True

                title = win32gui.GetWindowText(hwnd)
                if not title:
                    return True

                cls = _get_window_class(hwnd)
                if cls in _SYSTEM_CLASSES:
                    return True

                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                if pid == self._own_pid:
                    return True

                # Resolve real PID for UWP/hosted windows
                pid = _resolve_real_pid(hwnd, pid)

                exe = _get_process_name(pid)

                # Exclude system overlays and tools
                if exe.lower() in _EXCLUDED_PROCESSES:
                    return True
                title_lower = title.lower()
                if any(p in title_lower for p in _EXCLUDED_TITLE_PATTERNS):
                    return True

                left, top, right, bottom = win32gui.GetWindowRect(hwnd)

                if (right - left) < 100 or (bottom - top) < 100:
                    return True

                windows.append({
                    "hwnd": hwnd,
                    "title": title,
                    "pid": pid,
                    "exe": exe,
                    "exe_path": _get_process_exe(pid),
                    "class": cls,
                    "rect": [left, top, right, bottom],
                })
            except Exception:
                pass
            return True

        win32gui.EnumWindows(callback, None)
        return windows

    def find_window(self, title: str = "", exe: str = "") -> dict | None:
        """Find a visible window by title or exe name (fuzzy match)."""
        title_lower = title.lower() if title else ""
        exe_lower = exe.lower() if exe else ""

        for w in self.enum_visible_windows():
            if title_lower and title_lower in w["title"].lower():
                return w
            if exe_lower and exe_lower in w["exe"].lower():
                return w
        return None


class WindowPickerOverlay:
    """Fullscreen overlay for interactive window selection.

    Two windows:
    - dim_win: fullscreen alpha=0.5 dimming (captured clicks)
    - border_win: small window around target, green border drawn at edges
      so the interior stays transparent (no click-through for border itself)
    """

    def __init__(self, picker: WindowPicker):
        self._picker = picker
        self._result_hwnd: int | None = None
        self._overlay_thread: threading.Thread | None = None
        self._active = False

    @property
    def is_active(self) -> bool:
        return self._active

    def show(self, callback) -> None:
        """Show the overlay non-blocking in a daemon thread."""
        if self._active:
            logger.warning("Overlay already active")
            return

        self._overlay_thread = threading.Thread(
            target=self._run_overlay, args=(callback,), daemon=True,
        )
        self._overlay_thread.start()

    def _run_overlay(self, callback) -> int | None:
        """Two-window overlay: dim_win (alpha) + border_win (transparent, edge border)."""
        import tkinter as tk

        logger.info("Overlay: starting")

        self._active = True
        self._result_hwnd = None

        windows = self._picker.enum_visible_windows()
        logger.info("Overlay: %d windows to choose from", len(windows))

        # ── dim_win: fullscreen darkening layer ──────────────────
        dim_win = tk.Tk()
        dim_win.attributes("-fullscreen", True)
        dim_win.attributes("-topmost", True)
        dim_win.overrideredirect(True)
        dim_win.configure(bg="black")
        dim_win.attributes("-alpha", 0.5)

        dim_canvas = tk.Canvas(dim_win, highlightthickness=0, bg="black")
        dim_canvas.pack(fill="both", expand=True)

        sw = dim_win.winfo_screenwidth()
        sh = dim_win.winfo_screenheight()
        dim_canvas.create_text(sw // 2, 30,
            text="Click a window to select  ·  Esc to cancel",
            fill="white", font=("Segoe UI", 13))
        logger.info("Overlay: dim_win %dx%d alpha=%s", sw, sh, dim_win.attributes("-alpha"))

        # ── border_win: green border around target ───────────────
        border_win = tk.Toplevel(dim_win)
        border_win.overrideredirect(True)
        border_win.attributes("-topmost", True)
        border_win.configure(bg="magenta")
        border_win.attributes("-transparentcolor", "magenta")

        b_canvas = tk.Canvas(border_win, highlightthickness=0, bg="magenta")
        b_canvas.pack(fill="both", expand=True)

        # Draw border as 4 thin rectangles at edges (NOT a filled rect)
        # This way the interior is magenta=transparent, no click-through.
        BW = 6  # border width
        top_bar = b_canvas.create_rectangle(0, 0, 0, BW, fill="#10a37f", outline="")
        bot_bar = b_canvas.create_rectangle(0, 0, 0, BW, fill="#10a37f", outline="")
        lft_bar = b_canvas.create_rectangle(0, 0, BW, 0, fill="#10a37f", outline="")
        rgt_bar = b_canvas.create_rectangle(0, 0, BW, 0, fill="#10a37f", outline="")
        label_bg = b_canvas.create_rectangle(0, 0, 0, 0, fill="#1a1a1a", outline="")
        label_id = b_canvas.create_text(0, 0, text="", fill="white", font=("Segoe UI", 13))

        # Start fullscreen (invisible magenta)
        border_win.geometry(f"{sw}x{sh}+0+0")

        logger.info("Overlay: entering mainloop")

        current_hover: dict | None = None

        def find_window_at(mx, my):
            for w in windows:
                wl, wt, wr, wb = w["rect"]
                if wl <= mx <= wr and wt <= my <= wb:
                    return w
            return None

        def update_highlight(found):
            if found:
                wl, wt, wr, wb = found["rect"]
                ww, hh = wr - wl, wb - wt
                logger.debug("Overlay: highlight hwnd=%d '%s' %dx%d+%d+%d",
                             found["hwnd"], found["title"], ww, hh, wl, wt)

                # Position border_win around target
                border_win.geometry(f"{ww}x{hh}+{wl}+{wt}")

                # Draw border as 4 edge bars
                b_canvas.coords(top_bar, 0, 0, ww, BW)
                b_canvas.coords(bot_bar, 0, hh - BW, ww, hh)
                b_canvas.coords(lft_bar, 0, 0, BW, hh)
                b_canvas.coords(rgt_bar, ww - BW, 0, ww, hh)

                # Label above the window
                exe_info = found['exe_path'] or found['exe'] or '?'
                label_text = f"  {found['title']}  ·  {exe_info}  (PID {found['pid']})  ·  {ww}×{hh}  "
                b_canvas.itemconfigure(label_id, text=label_text)
                bbox = b_canvas.bbox(label_id)
                tw = (bbox[2] - bbox[0]) + 12 if bbox else 200
                th = (bbox[3] - bbox[1]) + 6 if bbox else 24
                lx, ly = 4, -th - 4
                if wt + ly < 0:
                    ly = 4
                b_canvas.coords(label_id, lx + 6, ly + th // 2)
                b_canvas.coords(label_bg, lx, ly, lx + tw, ly + th)
            else:
                # Hide border (off-screen)
                border_win.geometry("1x1+-10+-10")
                b_canvas.coords(label_bg, 0, 0, 0, 0)
                b_canvas.itemconfigure(label_id, text="")

        def on_motion(event):
            nonlocal current_hover
            found = find_window_at(event.x_root, event.y_root)
            if found is not current_hover:
                current_hover = found
                logger.debug("Overlay: hover=%s", found["title"] if found else "none")
                update_highlight(found)

        def on_click(_event=None):
            if current_hover:
                logger.info("Overlay: clicked hwnd=%d '%s'", current_hover["hwnd"], current_hover["title"])
                self._result_hwnd = current_hover["hwnd"]
                dim_win.destroy()

        def on_key(event):
            if event.keysym == "Escape":
                logger.info("Overlay: Esc")
                self._result_hwnd = None
                dim_win.destroy()

        # Bind to both windows (motion on dim_win, click on both)
        dim_canvas.bind("<Motion>", on_motion)
        dim_canvas.bind("<Button-1>", on_click)
        b_canvas.bind("<Motion>", on_motion)
        b_canvas.bind("<Button-1>", on_click)
        dim_win.bind("<Escape>", on_key)
        border_win.bind("<Escape>", on_key)

        dim_win.mainloop()
        self._active = False

        result = self._result_hwnd
        logger.info("Overlay: exited, result=%s", result)
        if callback:
            callback(result)
        return result
