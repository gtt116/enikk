# Enikk

Self-improving GUI Agent for desktop automation, built on [hermes-agent](https://github.com/NousResearch/hermes-agent).

Enikk exposes an HTTP API and IM bridge that lets AI agents orchestrate desktop automation tasks. It captures screenshots, detects UI elements via YOLO + OCR, and simulates input to automate workflows in games and applications.

## Features

- **HTTP API** — FastAPI server with endpoints for screenshots, state detection, clicks, and agent control
- **IM Bridge** — Chat with your agent via Telegram, Discord, Slack, DingTalk, or QQ
- **Web Dashboard** — Real-time SSE streaming of agent actions, tool calls, and results
- **Session Management** — Persistent sessions with conversation history and steer capability
- **UI Parsing** — YOLO icon detection + RapidOCR text recognition with normalized [0,1000] coordinates
- **Self-Improving** — Post-session reviews extract lessons to persistent memory
- **Multi-Model Support** — Works with any OpenAI-compatible API (Qwen, Claude, GPT, etc.)

## Architecture

```
CLI (cli.py) ──HTTP──▶ FastAPI Server (server.py) ──▶ Eternity (session manager)
                                                      ├── AIAgent (hermes-agent)
                                                      ├── StreamChannel (pub/sub)
                                                      └── IMBridge (gateway adapters)

Server ──▶ AppController ──▶ Daemon
                              ├── ProcessManager (launch/login/game)
                              ├── CaptureMethod (pyautogui)
                              ├── GameAnalyzer (RapidOCR + CV)
                              ├── UIParser (YOLO + OCR fusion)
                              └── Input (pyautogui/win32)
```

## Installation

### Prerequisites

- Python 3.10+
- Windows 10/11 (for window capture and input simulation)
- hermes-agent (installed as dependency)

### Install hermes-agent

Enikk is built on hermes-agent, which provides the AI agent framework, tool system, and gateway adapters.

```bash
pip install hermes-agent
```

hermes-agent will be installed automatically when you install enikk, but you can install it separately if you want to use its CLI first:

```bash
# Check hermes is installed
hermes --version

# Run hermes setup wizard (configures LLM provider, tools, etc.)
hermes setup
```

The hermes setup wizard configures:
- **Model & Provider** — API key and endpoint for your LLM (OpenAI, Anthropic, local models)
- **Terminal Backend** — Optional shell command execution
- **Agent Settings** — Max iterations, context length, etc.
- **Messaging Platforms** — IM bot tokens (Telegram, Discord, etc.)
- **Tools** — Enable/disable bundled tools

Configuration is stored in `~/.hermes/config.yaml` and `~/.hermes/.env`.

### Install Enikk

```bash
# Clone the repository
git clone https://github.com/yourusername/enikk.git
cd enikk

# Create virtual environment
uv venv --seed
.venv\Scripts\Activate.ps1  # Windows
# source .venv/bin/activate  # Linux/Mac

# Install in editable mode
uv pip install -e .
```

### Configure Enikk

Copy the example config and edit it:

```bash
cp config.example.yaml config.yaml
# Edit config.yaml with your settings
```

Key configuration sections:

```yaml
# LLM model settings
model:
  default: "qwen3.6-plus"
  base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1"
  api_key: "sk-your-api-key"
  max_tokens: 4096

# IM bridge (optional)
im:
  telegram:
    enabled: true
    token: "your-bot-token"

# Server settings
server:
  host: "127.0.0.1"
  port: 18931
```

## Usage

### Start the daemon

```bash
enikk daemon --config config.yaml
```

The daemon starts the HTTP server and IM bridge (if configured). You'll see:

```
  _____   _   _  _____  _  __  _  __
 |  ___| | \ | ||_   _|| |/ / | |/ /
 | |__   |  \| |  | |  | ' /  | ' /
 |  __|  | . ` |  | |  |  <   |  <
 | |___  | |\  | _| |_ | . \  | . \
 |_____| |_| \_||_____||_|\_\ |_|\_\

 Enikk - Self-improving GUI Agent

 Dashboard: http://127.0.0.1:18931/
```

### Web Dashboard

Open http://127.0.0.1:18931/ in your browser. The dashboard provides:

- **Session list** — View and switch between agent sessions
- **Chat interface** — Send tasks and follow-up messages
- **Real-time streaming** — Watch tool calls and results as they happen
- **Screenshot viewer** — See what the agent sees
- **URL sync** — Session ID appears in URL for sharing/bookmarking

### IM Bridge

Chat with your agent via your configured IM platform:

```
You: Launch the game and navigate to daily missions
🤖: [streams tool calls and results]
    [sends screenshots when tools capture them]
    [sends final response when done]

You: /new Start a new session
🤖: [stops previous session, starts fresh]

You: /stop
🤖: 🛑 已停止会话: abc123

You: /tools
🤖: 🔧 工具调用通知: 🔕 已关闭

You: /help
🤖: 🤖 **Enikk 助手**
    🆕 /new [提示词] - 新建会话
    🛑 /stop - 停止当前会话
    🔧 /tools - 切换工具调用通知
    ℹ️ /help - 显示帮助
```

### CLI Commands

```bash
# Take a screenshot (requires daemon running)
enikk screenshot -o screen.jpg

# Click at coordinates [0,1000] (requires daemon running)
enikk click 500 300

# Run agent directly (one-shot, no daemon)
enikk agent "navigate to settings" --config config.yaml
enikk agent "complete the current event" --model qwen3.6-plus
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/api/state` | Current game state (on-demand capture + analyze) |
| GET | `/api/state/stream` | SSE state stream |
| GET | `/api/screenshot` | Screenshot base64 + OCR + YOLO UI elements |
| GET | `/api/process` | Game process info |
| POST | `/api/action/launch` | Launch game (async, returns immediately) |
| GET | `/api/action/click` | Click at (x, y) — normalized [0,1000] |
| POST | `/api/action/exit` | Terminate game |
| GET | `/api/info` | API metadata + endpoint list |
| POST | `/api/sessions` | Create new agent session |
| POST | `/api/sessions/{id}/steer` | Send follow-up message to running session |
| GET | `/api/sessions/{id}/stream` | SSE stream of agent events |
| GET | `/api/sessions` | List recent sessions |
| DELETE | `/api/sessions/{id}` | Delete a session |

## Configuration

### config.example.yaml

```yaml
# Model configuration
model:
  default: "qwen3.6-plus"
  base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1"
  api_key: "sk-your-api-key-here"
  max_tokens: 4096

# Server settings
server:
  host: "127.0.0.1"
  port: 18931

# Logging
log_level: "INFO"

# IM bridge (optional — uncomment to enable)
# im:
#   telegram:
#     enabled: true
#     token: "your-telegram-bot-token"
#   discord:
#     enabled: true
#     token: "your-discord-bot-token"
#   slack:
#     enabled: true
#     token: "xoxb-your-slack-bot-token"
#   dingtalk:
#     enabled: true
#     token: "your-dingtalk-bot-token"
#   qqbot:
#     enabled: true
#     app_id: "your-qq-app-id"
#     token: "your-qq-bot-token"
#     secret: "your-qq-bot-secret"

# Custom apps (optional — for game-specific automation)
# apps:
#   nikke:
#     launcher_path: "D:\\NIKKE\\launcher.exe"
#     game_path: "D:\\NIKKE\\game.exe"
#     window_title: "NIKKE"
```

### Environment Variables

You can also configure via environment variables (override config.yaml):

```bash
export ENIKK_MODEL_API_KEY="sk-your-api-key"
export ENIKK_MODEL_BASE_URL="https://api.openai.com/v1"
export ENIKK_MODEL_DEFAULT="gpt-4o"
export ENIKK_SERVER_HOST="0.0.0.0"
export ENIKK_SERVER_PORT="8080"
```

## Development

```bash
# Install development dependencies
uv pip install -e ".[dev]"

# Run tests
pytest

# Type checking
mypy enikk

# Linting
ruff check enikk
```

## How It Works

### Session Lifecycle

1. **Create session** — User sends a task via web dashboard or IM
2. **Agent thread** — Eternity spawns a background thread running hermes AIAgent
3. **Tool calls** — Agent calls tools (screenshot, click, wait) via AppController
4. **Streaming** — StreamChannel publishes events to SSE subscribers (web + IM)
5. **Completion** — Agent finishes, final response sent to all subscribers
6. **Persistence** — Session history saved to SessionDB for future context

### UI Parsing Pipeline

```
Screenshot (pyautogui)
    ↓
Compress to max 1366px
    ↓
    ├── RapidOCR → text detections
    └── YOLO → icon detections
    ↓
Overlap resolution (prefer OCR text inside YOLO boxes)
    ↓
Normalize bboxes to [0,1000]
    ↓
UI elements with labels and coordinates
```

### IM Bridge Architecture

Enikk reuses hermes-agent's gateway platform adapters (Telegram, Discord, etc.) without reimplementing protocol logic:

```
IM Message (Telegram/Discord/etc.)
    ↓
hermes PlatformAdapter
    ↓
IMBridge._handle_message()
    ↓
Eternity session (create or steer)
    ↓
StreamChannel events
    ↓
GatewayStreamConsumer (progressive message updates)
    ↓
IM Response (with tool call hints and screenshots)
```

## License

MIT License. See [LICENSE](LICENSE).

## Contributing

Contributions welcome! Please open an issue or PR on GitHub.

## Acknowledgments

Built on [hermes-agent](https://github.com/NousResearch/hermes-agent) by NousResearch.
