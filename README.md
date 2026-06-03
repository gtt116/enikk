<p align="center">
  <img src="enikk/static/enikk-logo.png" alt="Enikk Logo" width="128" />
</p>

# Enikk

**Self-improving GUI Agent Framework for desktop automation.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-lightgrey)]()

Enikk is an AI agent that watches your screen, understands what it sees, and operates any desktop application — autonomously. It learns from experience, extracts reusable skills, and gets smarter every time you use it.

---

## ✨ Key Features

### 🧠 Self-improving
After each task, Enikk automatically reviews what happened and extracts reusable skills into persistent memory. The agent gets smarter the more you use it.

### 💰 Smart & Cost-efficient
Enikk uses a multi-layer perception system (YOLO + OCR + VLM) that minimizes AI costs. Most operations never need expensive vision models — saving you money.

### ⚡ Zero Code Required
Configure everything through the Web Dashboard. No programming, no scripts, no YAML editing — just point-and-click setup.

### 🖥️ Multi-app Support
Control multiple applications simultaneously. Enikk auto-discovers windows and can switch between apps during a task.

### 👁️ Fully Observable
Watch every step in the Web Dashboard: screenshots, detected elements, reasoning, and actions. No black boxes — complete transparency.

### 🔒 Local & Private
Runs entirely on your machine. Your data, screenshots, and credentials never leave your computer (except for AI API calls).

---

## 🏗 Architecture

**Data flow:**
1. **Capture** — Take a screenshot of the target application window
2. **Parse** — YOLO detects UI elements, OCR reads text, results normalized to `[0,1000]` coordinates
3. **Decide** — LLM analyzes structured data and decides what to do
4. **Act** — Click, type, or wait based on the decision
5. **Review** — After the session, lessons are extracted to persistent skill files

---

## 🚀 Getting Started

### Download & Run

1. **Download** the latest release from [GitHub Releases](https://github.com/gtt116/enikk/releases)
2. **Extract** the zip file
3. **Run** `enikk.exe` as Administrator (UAC prompt will appear)
4. **Open** — the dashboard opens automatically in a native window

That's it. No installation, no Python, no dependencies.

> [!NOTE]
> Administrator privileges are required to control application windows and perform automated operations.

---

## 🎮 Supported Applications

Enikk can control **any Windows desktop application**. Built-in app profiles:

| App | Profile | Notes |
|---|---|---|
| NIKKE | ✅ Built-in | Game automation |
| Wuthering Waves | ✅ Built-in | Game automation |
| Any Windows app | ✅ Custom | Add via config |

### Adding a Custom App

Open the **Settings** page in the dashboard, fill in your app's path and name, and click **Save**. Enikk will auto-discover the window and start operating.

---

## 🤖 IM Bridge

Talk to Enikk through your favorite messaging platform. Supported:

- **QQ**

Each chat session maps to an independent Enikk session with full conversation history and streaming.

Configure in `config.yaml`:

```yaml
im:
  qqbot:
    enabled: true
    app_id: "..."
    app_secret: "..."
```

---

## 🛠 For Developers

### Build from Source

```bash
git clone https://github.com/gtt116/enikk.git
cd enikk
uv venv --seed
.venv\Scripts\Activate.ps1
pip install -e .
enikk daemon
```

### Build Executable

```powershell
# Debug build (with console)
.\build.bat

# Release build (without console)
.\build.bat --release
```

Generated files:
- Debug mode: `dist/enikk-debug/enikk-debug.exe`
- Release mode: `dist/enikk/enikk.exe` and `dist/enikk.zip`

> [!IMPORTANT]
> Release executable requires administrator privileges (UAC) to run. It will prompt for confirmation when launched.

---

## 📦 Dependencies & Credits

Enikk stands on the shoulders of giants:

| Project | License | Role |
|---|---|---|
| [Hermes Agent](https://github.com/NousResearch/hermes-agent) (NousResearch) | MIT | AI Agent framework, tool system, memory, IM Platform |
| [OmniParser](https://github.com/microsoft/OmniParser) (Microsoft) | CC-BY-4.0 | YOLO model weights for UI element detection |
| [RapidOCR](https://github.com/RapidAI/RapidOCR) | Apache 2.0 | ONNX-based Chinese OCR engine |

Enikk's own code is **MIT License** — see [LICENSE](LICENSE).

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.
