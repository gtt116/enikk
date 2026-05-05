# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Enikk — NIKKE: Goddess of Victory CLI

Automation tool for the NIKKE game. Designed as a daemon that exposes an HTTP API; external AI agents consume the JSON state and orchestrate decisions.

## Architecture

```
CLI (cli.py) ──HTTP──▶ FastAPI Server (server.py) ──▶ Daemon (daemon.py)
                                                      ├── ProcessManager (process.py)
                                                      ├── CaptureMethod (capture.py)
                                                      ├── GameAnalyzer (analyzer.py)
                                                      └── Input (input.py)
```

| Module | Responsibility |
|--------|---------------|
| `cli.py` | Single entrypoint with `argparse` subcommands (daemon + client commands) |
| `server.py` | FastAPI HTTP server with middleware (Ready, Timing). Launch endpoint runs in a background thread via `threading.Thread(daemon=True)` to avoid blocking the event loop |
| `daemon.py` | Central `Daemon` class wiring process, capture, analyzer, and input |
| `process.py` | Full launch flow: Launcher → Login → Game via `app_start()`. Split into `_Process` base, `LauncherProcess` (adds OCR login), `GameProcess` |
| `capture.py` | pyautogui screenshots of game window region via EnumWindows + psutil path matching |
| `analyzer.py` | RapidOCR + CV-based state detection (loading, lobby, popup, launcher, login) |
| `input.py` | Foreground input via pyautogui/pynput; background input via win32 PostMessage |
| `config.py` | Dataclass config with YAML + env override support |

## Development Commands

```powershell
# Virtual environment
uv venv --seed
.venv\Scripts\Activate.ps1

# Install (editable)
uv pip install -e .

# Run daemon
enikk daemon --launch --debug

# Run without auto-launch (game already running)
enikk daemon

# Client commands (requires daemon running)
enikk state
enikk screenshot -o screen.jpg
enikk do confirm
enikki health
enikk process
enikk launch       # async — returns immediately; check progress with `enikk state`
```

## Key Design Decisions

- **CLI does atomic operations; agents orchestrate flows.** The CLI exposes deterministic endpoints (state, screenshot, confirm, etc.) without complex branching logic.
- **Launch is async.** `/api/action/launch` starts the launch in a background thread via `threading.Thread(daemon=True)` and returns immediately. The client should poll `/api/state` or `/api/process` for progress. A `threading.Event` is used for cooperative cancellation, triggered by Ctrl-C signal handler.
- **Foreground-only input.** The game uses Unity/Windows input that requires the window to be in the foreground. pyautogui captures global screenshots and simulates input.
- **RapidOCR for text detection.** Uses `rapidocr-onnxruntime` (CPU, ~16MB model) instead of cloud-based OCR.
- **Build backend** uses standard `setuptools.build_meta`. Package discovery is constrained to `enikk*` to avoid accidentally including the `screenshots/` directory.

## Conventions

- **Imports at top of file.** All `import` statements must be placed at the top of the file, never inline or inside functions.
- **No Co-Authored-By in commits.** Do not include `Co-Authored-By` trailer in git commit messages.
