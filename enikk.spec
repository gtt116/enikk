# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Enikk — Self-improving GUI Agent."""

import os

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_dynamic_libs, collect_submodules

# ── Build configuration ─────────────────────────────────────────────────
# ENIKK_RELEASE=1 build.bat --release → no console window
# default (debug) → console window visible
RELEASE = os.environ.get('ENIKK_RELEASE', '0') == '1'

block_cipher = None

# ── Project root (where this .spec file lives) ─────────────────────────
SPEC_DIR = SPECPATH if isinstance(SPECPATH, str) else str(SPECPATH)
ENIKK_PKG = os.path.join(SPEC_DIR, 'enikk')

# ── onnxruntime: only the CAPI DLLs (avoid pulling torch/scipy/pyarrow) ─
ort_binaries = collect_dynamic_libs('onnxruntime')

# ── rapidocr_onnxruntime: bundled model files ──────────────────────────
rapidocr_datas = collect_data_files('rapidocr_onnxruntime')

# ── uvicorn: logging config, protocol modules ──────────────────────────
uvicorn_datas = collect_data_files('uvicorn')
uvicorn_hiddenimports = collect_submodules('uvicorn')

# ── pywebview: EdgeChromium runtime support ────────────────────────────
webview_datas, webview_binaries, webview_hiddenimports = collect_all('webview')

# ── hermes-agent gateway assets ────────────────────────────────────────
gateway_datas = collect_data_files('gateway')

# ── Data files from the enikk package ──────────────────────────────────
enikk_datas = [
    # Static web assets (HTML, CSS, JS, fonts, icons)
    (os.path.join(ENIKK_PKG, 'static'), 'enikk/static'),
    # Bundled skills
    (os.path.join(ENIKK_PKG, 'skills'), 'enikk/skills'),
]

# ── Bundled weights (ONNX models for YOLO + OCR) ──────────────────────
WEIGHTS_DIR = os.path.join(SPEC_DIR, 'weights')
if os.path.isdir(WEIGHTS_DIR):
    enikk_datas.append((WEIGHTS_DIR, 'weights'))

# ── Hidden imports ─────────────────────────────────────────────────────
hiddenimports = [
    # ── hermes-agent modules ───────────────────────────────────────────
    'run_agent',
    'tools',
    'tools.registry',
    'tools.skills_sync',
    'hermes_state',
    'hermes_bootstrap',
    'hermes_constants',
    'hermes_logging',
    'hermes_time',
    'hermes_cli',
    'hermes_cli.auth',
    'hermes_cli.config',
    'hermes_cli.models',
    'hermes_cli.runtime_provider',
    'model_tools',
    'plugins',
    'providers',
    'toolsets',
    'toolset_distributions',
    'trajectory_compressor',
    'utils',
    'acp_adapter',
    'agent',
    'batch_runner',
    'cli',
    'cron',
    'gateway',
    'tui_gateway',

    # ── uvicorn ────────────────────────────────────────────────────────
    'uvicorn.logging',
    'uvicorn.loops',
    'uvicorn.loops.auto',
    'uvicorn.protocols',
    'uvicorn.protocols.http',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.websockets',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.lifespan',
    'uvicorn.lifespan.on',

    # ── FastAPI / Starlette ────────────────────────────────────────────
    'fastapi',
    'starlette',
    'starlette.staticfiles',
    'starlette.responses',
    'anyio',
    'anyio._backends',
    'anyio._backends._asyncio',
    'httptools',
    'websockets',

    # ── pywebview ──────────────────────────────────────────────────────
    'webview',
    'webview.platforms.edgechromium',

    # ── pywin32 / Windows ─────────────────────────────────────────────
    'win32gui',
    'win32process',
    'win32con',
    'win32api',
    'win32ui',
    'win32event',
    'ctypes.wintypes',
    'pywintypes',
    'pythoncom',

    # ── OpenCV / numpy ────────────────────────────────────────────────
    'cv2',
    'numpy',

    # ── OCR / ML ──────────────────────────────────────────────────────
    'onnxruntime',
    'onnxruntime.capi',
    'onnxruntime.capi._pybind_state',
    'rapidocr_onnxruntime',
    'pyclipper',
    'shapely',

    # ── Input / capture ───────────────────────────────────────────────
    'pyautogui',
    'pynput',
    'pynput.mouse',
    'pynput.keyboard',
    'mss',
    'mss.windows',
    'PIL',
    'PIL.Image',
    'PIL.ImageDraw',
    'PIL.ImageFont',

    # ── YAML ──────────────────────────────────────────────────────────
    'yaml',

    # ── psutil ────────────────────────────────────────────────────────
    'psutil',

    # ── openai (used by /api/model/test) ──────────────────────────────
    'openai',
    'httpx',
    'httpcore',

    # ── stdlib ────────────────────────────────────────────────────────
    'queue',
    'uuid',
    'dataclasses',
    'concurrent.futures',
    'shutil',
    'logging.handlers',
]

# Merge all collected hidden imports
all_hiddenimports = list(set(
    hiddenimports
    + webview_hiddenimports
    + uvicorn_hiddenimports
))

a = Analysis(
    ['pyinstaller_entry.py'],
    pathex=[SPEC_DIR],
    binaries=ort_binaries + webview_binaries,
    datas=enikk_datas + rapidocr_datas + gateway_datas + uvicorn_datas,
    hiddenimports=all_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Heavy deps not needed at runtime
        'torch', 'torchvision', 'torchaudio',
        'pyarrow',
        'onnxruntime.quantization', 'onnxruntime.transformers',
        'onnxruntime.tools', 'onnxruntime.datasets',
        # GUI / dev / test
        'tkinter', 'matplotlib', 'pandas',
        'IPython', 'jupyter', 'notebook',
        'pytest', 'ruff', 'mypy',
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# Output name based on build mode
output_name = 'enikk' if RELEASE else 'enikk-debug'

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=output_name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=not RELEASE,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(ENIKK_PKG, 'static', 'enikk-logo.ico'),
    uac_admin=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name=output_name,
)
