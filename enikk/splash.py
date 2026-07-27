"""Lightweight splash screen shown during Enikk startup.

Uses tkinter in a daemon thread so the user sees immediate feedback
while heavy imports and initialisation run on the main thread.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Optional


class SplashScreen:
    """Borderless splash window with logo and animated status text."""

    _WIDTH = 500
    _HEIGHT = 360
    _BG = "#1a1a2e"
    _FG = "#e0e0e0"
    _ACCENT = "#7c3aed"

    def __init__(self, icon_path: Path, version: str) -> None:
        self._icon_path = icon_path
        self._version = version
        self._root: Optional[Any] = None
        self._status_var: Optional[Any] = None
        self._thread: Optional[threading.Thread] = None
        self._closed = threading.Event()
        self._failed = False

    # ── Public API ──────────────────────────────────────────────────────

    def show(self) -> None:
        """Create the splash window in a daemon thread."""
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="splash",
        )
        self._thread.start()

    def update_status(self, text: str) -> None:
        """Update the status label (thread-safe via tkinter ``after``).

        Note: cross-thread tkinter after() is not officially guaranteed safe,
        but works reliably on CPython/Windows due to GIL serialization.
        """
        if self._root and self._status_var:
            try:
                self._root.after(0, self._status_var.set, text)
            except Exception:
                pass

    def close(self) -> None:
        """Signal the splash window to close.

        Non-blocking: signals the daemon thread and returns immediately.
        The daemon thread will clean itself up on process exit.
        """
        self._closed.set()
        if self._root:
            try:
                # Note: cross-thread tkinter after() is not officially guaranteed
                # safe, but works reliably on CPython/Windows due to GIL serialization.
                self._root.after(0, self._destroy)
            except Exception:
                pass

    def show_error(self, message: str) -> None:
        """Display an error on the splash and block until closed.

        Used during startup failures so the user sees the error even in
        release builds (no console window). Blocks indefinitely — the
        splash stays open until the user clicks it or the process exits.
        Falls back to Windows MessageBox if tkinter is not available.
        """
        if self._root and self._status_var:
            try:
                self._root.after(0, self._show_error_ui, message)
            except Exception:
                pass
            # Block until close() is called (user clicks or process exits)
            self._closed.wait()
        else:
            # Tkinter not available (e.g. frozen app) — use MessageBox
            self._show_error_messagebox(message)

    def _show_error_ui(self, message: str) -> None:
        """Update splash UI to show error (must run on tkinter thread)."""
        try:
            import tkinter as tk
            if not self._root or not self._status_var:
                return
            # Change status to red error text
            self._status_var.set("❌ 启动失败")
            # Add error detail label
            detail = tk.Label(
                self._root, text=message[:200],
                font=("Segoe UI", 9), fg="#ff6b6b", bg=self._BG,
                wraplength=self._WIDTH - 40, justify="left",
            )
            detail.pack(pady=(10, 0), padx=20)
            # Add click-to-close hint
            hint = tk.Label(
                self._root, text="点击任意位置关闭",
                font=("Segoe UI", 8), fg="#888888", bg=self._BG,
            )
            hint.pack(pady=(15, 0))
            # Change accent bar to red
            for child in self._root.winfo_children():
                if isinstance(child, tk.Frame):
                    child.configure(bg="#ff4444")
            # Bind click anywhere on the window to close
            def _on_click(*_):
                self.close()
            self._root.bind("<Button-1>", _on_click)
            for child in self._root.winfo_children():
                child.bind("<Button-1>", _on_click)
        except Exception:
            pass

    @staticmethod
    def _show_error_messagebox(message: str) -> None:
        """Fallback: show error via Windows MessageBox when tkinter is unavailable."""
        try:
            import ctypes
            MB_OK = 0x0
            MB_ICONERROR = 0x10
            ctypes.windll.user32.MessageBoxW(
                0, message[:500], "Enikk — 启动失败", MB_OK | MB_ICONERROR,
            )
        except Exception:
            pass
        # Also write to log file next to the exe
        try:
            import os
            import sys
            exe_dir = os.path.dirname(sys.executable)
            log_path = os.path.join(exe_dir, "enikk_error.log")
            with open(log_path, "w", encoding="utf-8") as f:
                f.write(message)
        except Exception:
            pass

    # ── Internals ───────────────────────────────────────────────────────

    def _run(self) -> None:
        """Thread target: build the tkinter window and poll for close."""
        try:
            import tkinter as tk
            from PIL import Image, ImageTk
        except ImportError:
            self._failed = True
            return

        # DPI awareness is set at process level in __main__.py before splash creation.

        root = tk.Tk()
        root.overrideredirect(True)
        root.configure(bg=self._BG)
        root.attributes("-topmost", True)

        # Centre on screen
        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        x = (sw - self._WIDTH) // 2
        y = (sh - self._HEIGHT) // 2
        root.geometry(f"{self._WIDTH}x{self._HEIGHT}+{x}+{y}")

        # Logo (resize to 80×80)
        try:
            img = Image.open(self._icon_path).resize((80, 80))
            photo = ImageTk.PhotoImage(img)
            tk.Label(root, image=photo, bg=self._BG).pack(pady=(40, 8))
            root._logo_ref = photo  # type: ignore[attr-defined]  # prevent GC
        except Exception:
            pass  # logo is optional

        # App name
        tk.Label(
            root, text="Enikk", font=("Segoe UI", 22, "bold"),
            fg=self._FG, bg=self._BG,
        ).pack()

        # Version
        tk.Label(
            root, text=f"v{self._version}",
            font=("Segoe UI", 10), fg="#888888", bg=self._BG,
        ).pack()

        # Status text (animated)
        status_var = tk.StringVar(value="Loading...")
        tk.Label(
            root, textvariable=status_var,
            font=("Segoe UI", 10), fg="#aaaaaa", bg=self._BG,
        ).pack(pady=(20, 0))

        # Accent bar at bottom
        bar = tk.Frame(root, height=3, bg=self._ACCENT)
        bar.pack(side="bottom", fill="x")

        self._root = root
        self._status_var = status_var

        # Animated dots
        self._dot_count = 0
        self._animate_dots()

        # Poll for close signal instead of mainloop()
        self._poll()

        # Guard: if close() was called between _root assignment and here,
        # _poll() already destroyed the window — skip mainloop to avoid TclError.
        if not self._closed.is_set():
            root.mainloop()

    def _animate_dots(self) -> None:
        """Cycle 'Loading', 'Loading.', 'Loading..', 'Loading...'."""
        if self._closed.is_set():
            return
        self._dot_count = (self._dot_count + 1) % 4
        dots = "." * self._dot_count
        base = self._status_var.get().rstrip(".") if self._status_var else "Loading"
        if self._status_var:
            self._status_var.set(f"{base}{dots}")
        if self._root:
            self._root.after(400, self._animate_dots)

    def _poll(self) -> None:
        """Check if close() was called from another thread."""
        if self._closed.is_set():
            self._destroy()
            return
        if self._root:
            self._root.after(100, self._poll)

    def _destroy(self) -> None:
        """Safely destroy the tkinter root."""
        if self._root:
            try:
                self._root.quit()
                self._root.destroy()
            except Exception:
                pass
            self._root = None
