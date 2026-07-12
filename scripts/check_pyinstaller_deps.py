#!/usr/bin/env python3
"""Check that PyInstaller spec includes all project dependencies."""

import re
import sys
from pathlib import Path


def extract_toml_deps(pyproject: Path) -> set[str]:
    """Extract dependency package names from pyproject.toml."""
    text = pyproject.read_text(encoding="utf-8")
    # Find dependencies = [...] block
    match = re.search(r'dependencies\s*=\s*\[(.*?)\]', text, re.DOTALL)
    if not match:
        return set()
    block = match.group(1)
    # Extract package names (before any version specifier or semicolon)
    deps = set()
    for line in block.splitlines():
        line = line.strip().strip('"').strip("'").strip(',')
        if not line or line.startswith('#'):
            continue
        # Package name is before any version specifier (>=, ==, ~=, etc.) or semicolon
        name = re.split(r'[>=<!~;\[\s]', line)[0].strip()
        if name:
            # Normalize: hyphens to underscores for import comparison
            deps.add(name.lower().replace('-', '_'))
    return deps


def extract_hidden_imports(spec: Path) -> set[str]:
    """Extract hidden import names from .spec file."""
    text = spec.read_text(encoding="utf-8")
    # Find hiddenimports = [...] block
    match = re.search(r'hiddenimports\s*=\s*\[(.*?)\]', text, re.DOTALL)
    if not match:
        return set()
    block = match.group(1)
    imports = set()
    for line in block.splitlines():
        line = line.strip().strip('"').strip("'").strip(',')
        if not line or line.startswith('#'):
            continue
        # Top-level module name (before first dot)
        top = line.split('.')[0].lower()
        if top:
            imports.add(top)
    return imports


def main():
    # scripts/ is one level below project root
    root = Path(__file__).resolve().parent.parent
    pyproject = root / "pyproject.toml"
    spec = root / "enikk.spec"

    if not pyproject.exists():
        print("ERROR: pyproject.toml not found")
        return 1
    if not spec.exists():
        print("ERROR: enikk.spec not found")
        return 1

    deps = extract_toml_deps(pyproject)
    hidden = extract_hidden_imports(spec)

    # Packages that PyInstaller auto-discovers or don't need explicit import
    # (includes distribution-name → import-name mappings)
    auto_discovered = {
        'yaml',           # pyyaml → yaml
        'pyyaml',         # distribution name
        'numpy',          # imported at module level
        'cv2',            # imported at module level
        'opencv_python',  # distribution name for cv2
        'fastapi',        # imported at module level
        'uvicorn',        # imported at module level
        'pydantic',       # imported by fastapi
        'starlette',      # imported by fastapi
        'httptools',      # uvicorn dependency
        'anyio',          # starlette dependency
        'websockets',     # uvicorn optional
        'PIL',            # imported at module level
        'pillow',         # distribution name for PIL
        'mss',            # imported at module level
        'pyautogui',      # imported at module level
        'pynput',         # imported at module level
        'psutil',         # imported at module level
        'openai',         # imported in server
        'anthropic',      # imported in server
        'httpx',          # imported by openai/anthropic
        'httpcore',       # httpx dependency
        'pystray',        # imported at module level
        'pywin32',        # distribution name
        'win32gui',       # pywin32, imported at module level
        'win32api',       # pywin32
        'win32process',   # pywin32
        'win32con',       # pywin32
        'win32ui',        # pywin32
        'win32event',     # pywin32
        'pywintypes',     # pywin32
        'pythoncom',      # pywin32
        'aiohttp',        # imported in im_bridge
        'croniter',       # imported in cron.store
        'pywebview',      # distribution name
        'webview',        # import name, collected via collect_all
        'hermes_agent',   # distribution name, individual modules in hiddenimports
        'onnxruntime_directml',  # distribution name
        'onnxruntime',    # import name
        'rapidocr_onnxruntime',  # both distribution and import name
    }

    missing = deps - hidden - auto_discovered
    if missing:
        print(f"WARNING: {len(missing)} dependencies may not be in PyInstaller spec:")
        for dep in sorted(missing):
            print(f"  - {dep}")
        print("\nAdd them to hiddenimports in enikk.spec or verify they're auto-discovered.")
        return 1
    else:
        print(f"OK: All {len(deps)} dependencies covered in spec or auto-discovered.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
