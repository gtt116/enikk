# Enikk — The CLI for NIKKE: Goddess of Victory

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
| `cli.py` | Single entrypoint with `argparse` subcommands |
| `server.py` | FastAPI HTTP server with middleware |
| `daemon.py` | Central daemon class wiring process, capture, analyzer, and input |
| `process.py` | Game launch flow: Launcher → Game |
| `capture.py` | pyautogui screenshots of game window region |
| `analyzer.py` | RapidOCR + CV-based state detection |
| `input.py` | Foreground input via pyautogui/pynput |
| `config.py` | Dataclass config with YAML + env override support |

## Quick Start

```powershell
# Install
uv venv --seed
.venv\Scripts\Activate.ps1
uv pip install -e .

# Start daemon
enikk daemon

# Start daemon with custom paths
enikk daemon --launcher-path "D:\NIKKE\launcher.exe" --game-path "D:\NIKKE\game.exe"

# Start daemon with config file
enikk daemon --config config.yaml
```

## CLI Commands

```bash
# Daemon
enikk daemon                         # Start the HTTP API server
enikk daemon --port 18931            # Custom port

# Client (requires daemon running)
enikk screenshot -o screen.jpg       # Download latest screenshot
enikk screenshot --debug             # With debug overlay
enikk screenshot -w 1920             # Resize to width
enikk screenshot -f png              # PNG format (default: jpeg)
enikk click 960 540                  # Click at screen coordinates
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/api/state` | Current game state (on-demand capture + analyze) |
| GET | `/api/state/stream` | SSE state stream |
| GET | `/api/screenshot` | Latest screenshot (JPEG) |
| GET | `/api/screenshot/raw` | Raw screenshot base64 + state |
| GET | `/api/process` | Game process info |
| POST | `/api/action/click` | Click at (x, y) |
| POST | `/api/action/launch` | Launch game |
| POST | `/api/action/exit` | Terminate game |

## Configuration

```yaml
# config.yaml
launcher_path: 'C:\Program Files\NIKKE\launcher\nikke_launcher.exe'
game_path: 'C:\Program Files\NIKKE\NIKKE\game\nikke.exe'
client_type: 'intl'     # intl or hmt
launch_timeout: 120
host: "127.0.0.1"
port: 18931
```

Supports environment variable overrides: `ENIKK_LAUNCHER_PATH`, `ENIKK_GAME_PATH`, `ENIKK_PORT`, `ENIKK_HOST`.

## Tech Stack

| Component | Library |
|-----------|---------|
| Screenshot | `pyautogui` |
| Image processing | OpenCV (cv2) |
| OCR | RapidOCR-ONNX |
| Web | FastAPI + Uvicorn |
| Process management | psutil |
| Input simulation | `pyautogui` + `pynput` |
