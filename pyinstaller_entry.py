"""Bootstrap script for PyInstaller — imports enikk package and runs main."""
import sys
import traceback
import faulthandler
import os
import threading

# Enable faulthandler to catch segfaults — write to log file
try:
    _exe_dir = os.path.dirname(sys.executable)
    _fault_log = open(os.path.join(_exe_dir, "enikk_crash.log"), "w", encoding="utf-8")
    faulthandler.enable(file=_fault_log, all_threads=True)
except Exception:
    faulthandler.enable()

# ── Thread-safe PyInstaller importer ────────────────────────────────────
# PyInstaller's frozen importer (pyimod02_importers) is NOT thread-safe:
# concurrent first-time imports from multiple threads cause access violations
# in the PYZ archive extractor (pyimod01_archive.extract).  This is a known
# issue — the zlib decompression and mmap access are not serialised.
# Fix: wrap exec_module with a lock so only one thread loads a module at a time.
if getattr(sys, "frozen", False):
    _import_lock = threading.Lock()
    for _finder in sys.meta_path:
        if type(_finder).__name__ == "PyiFrozenImporter":
            _orig_exec = _finder.exec_module

            def _safe_exec(module, _orig=_orig_exec, _lock=_import_lock):
                with _lock:
                    _orig(module)

            _finder.exec_module = _safe_exec
            break


def _show_error(msg: str) -> None:
    """Display error to user. MessageBox in release mode, console in debug."""
    detail = traceback.format_exc()
    full = f"{msg}\n\n{detail}"

    # Try Windows MessageBox (works in release mode without console)
    try:
        import ctypes
        MB_OK = 0x0
        MB_ICONERROR = 0x10
        ctypes.windll.user32.MessageBoxW(
            0, full, "Enikk — Startup Error", MB_OK | MB_ICONERROR,
        )
    except Exception:
        pass

    # Also write to a log file next to the exe
    try:
        import os
        exe_dir = os.path.dirname(sys.executable)
        log_path = os.path.join(exe_dir, "enikk_error.log")
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(full)
    except Exception:
        pass

    # Console fallback (debug mode)
    print(full, file=sys.stderr)
    try:
        input("Press Enter to exit...")
    except Exception:
        pass


try:
    from enikk.__main__ import main
    main()
except Exception as e:
    _show_error(f"Failed to start Enikk: {e}")
    sys.exit(1)
