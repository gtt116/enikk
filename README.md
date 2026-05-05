# 🌟 Enikk — The CLI for NIKKE: Goddess of Victory

> **Enikk（伊妮克）** — 你的 NIKKE 指挥官，自动化一切日常。

**AI Native CLI**：专为 AI Agent 消费设计的胜利女神自动化工具。集 **感知 + 决策辅助 + 执行** 于一体。

## Design Philosophy

```
┌──────────┐          ┌──────────┐
│  Enikk   │─────────▶│  Agent   │
│  (看+做)  │  JSON    │  (大脑)   │
└──────────┘          └──────────┘
```

| 组件 | 职责 |
|------|------|
| **Enikk** | **看**（游戏状态感知）+ **做**（后台点击/按键） |
| **Agent** | **决策**（拿到状态后编排下一步） |

## CLI Design Principles

**有分支 → Agent 判断，无分支 → CLI 封装。**

| CLI 封装（确定性） | Agent 决策（有分支） |
|-------------------|---------------------|
| `enikk state` — 返回状态 | 判断"当前该做什么" |
| `enikk do confirm` — 点击确认 | 登录流程（多状态循环） |
| `enikk screenshot` — 下载截图 | 自动日常（任务进度不同） |
| `enikk launch` — 启动游戏 | 错误恢复（弹窗卡住怎么办） |

**一句话：CLI 做手脚（原子操作），Agent 做大脑（流程编排）。**

## Quick Start

```bash
cd E:\openclaw-code\src\enikk

# 方式1：完整启动流程（启动器 → 登录 → 游戏）
.\.venv\Scripts\python.exe -m enikk daemon --launch

# 方式2：仅 API（游戏已在运行）
.\.venv\Scripts\python.exe -m enikk daemon

# 方式3：自定义路径
.\.venv\Scripts\python.exe -m enikk daemon --launcher-path "D:\NIKKE\launcher.exe" --game-path "D:\NIKKE\game.exe"

# 方式4：调试模式（保存截图）
.\.venv\Scripts\python.exe -m enikk daemon --debug
```

## CLI Commands

```bash
# 查询（快速返回）
enikk state                    # 当前游戏状态，输出 JSON
enikk health                   # daemon 是否存活
enikk process                  # 游戏进程信息

# 操作
enikk launch                   # 启动游戏（通过 daemon API）
enikk screenshot -o screen.jpg # 下载截图
enikk capture                  # 强制截图+分析

# 执行（后台交互）
enikk do confirm               # OCR 找到"确认"并点击
enikk do connect               # OCR 找到"点击连接"并点击
enikk do exit                  # 强制终止游戏进程

# 全局参数
enikk --server 127.0.0.1:18931 state  # 指定 daemon 地址
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | 健康检查 |
| GET | `/api/state` | **当前游戏状态**（按需截图+分析） |
| GET | `/api/state/stream` | SSE 状态流（状态变化时推送） |
| GET | `/api/screenshot` | 最新截图（带状态叠加，JPEG） |
| GET | `/api/screenshot/raw` | 原始截图 base64 + 状态 |
| GET | `/api/process` | 游戏进程信息 |
| GET | `/api/templates` | 已加载的模板列表 |
| POST | `/api/action/launch` | 启动游戏 |
| POST | `/api/action/screenshot` | 强制截图+分析 |
| POST | `/api/action/confirm` | OCR 找"确认"并点击 |
| POST | `/api/action/connect` | OCR 找"点击连接"并点击 |
| POST | `/api/action/exit` | 终止游戏进程 |

## Game States

| State | Description | Suggested Action |
|-------|-------------|-----------------|
| `not_running` | 游戏未运行 | `enikk launch` |
| `launching` | 启动中 | 等待 |
| `login_screen` | 登录界面 | `enikk do connect` |
| `loading` | 加载画面 | 等待 |
| `lobby` | **大厅** ✅ | 可以执行任务 |
| `in_battle` | 战斗中 | 等待结束 |
| `monthly_pass` | 月卡弹窗 | `enikk do confirm` |
| `popup` | 弹窗 | `enikk do confirm` |
| `unknown` | 未知 | 截图给 Agent 判断 |

## Response Format

```json
{
  "game_state": "lobby",
  "state_reason": "template_match:lobby-icon",
  "actions": ["idle"],
  "timestamp": "2026-05-05T17:20:00",
  "analysis_time_ms": 45.2,
  "screenshot_age_ms": 150.3,
  "resolution": "1920x1080"
}
```

## Detection Methods

| Method | Used For |
|--------|----------|
| **pyautogui.screenshot** | 前台截图（游戏窗口需在前台） |
| **亮度直方图** | 加载画面检测 |
| **颜色检测（HSV）** | 战斗状态 |
| **模板匹配（CV2）** | 月卡/大厅 |
| **PaddleOCR** | 文字识别 |

## Configuration

```yaml
# config.yaml
launcher_path: 'C:\Program Files\NIKKE\launcher\nikke_launcher.exe'
game_path: 'C:\Program Files\NIKKE\NIKKE\game\nikke.exe'
client_type: 'intl'  # intl 或 hmt
window_class: 'UnityWndClass'
launch_timeout: 120
ocr_max_width: 1024
host: "127.0.0.1"
port: 18931
save_screenshots: false
screenshot_dir: "E:\\openclaw-code\\src\\enikk\\screenshots"
```

支持环境变量覆盖：
```bash
ENIKK_LAUNCHER_PATH="xxx" ENIKK_GAME_PATH="yyy" enikk daemon
```

## Query Examples

```powershell
# 查看当前状态
Invoke-RestMethod http://127.0.0.1:18931/api/state

# SSE 流式监听
curl -N http://127.0.0.1:18931/api/state/stream

# 获取截图
Invoke-WebRequest http://127.0.0.1:18931/api/screenshot -OutFile screenshot.jpg
```

## Tech Stack

| Component | Library | Notes |
|-----------|---------|-------|
| 截图 | `pyautogui` | 前台截图（游戏窗口需在前台） |
| 图像处理 | OpenCV (cv2) | 模板匹配 + 颜色/直方图分析 |
| OCR | RapidOCR-ONNX | 轻量模型，~16MB，CPU 运行 |
| Web | FastAPI + Uvicorn | HTTP API + SSE |
| 进程管理 | psutil | 按用户名匹配，避免误杀 |
| 输入模拟 | `pyautogui` + `pynput` | 前台操作（参考 NIKKEAutoScript） |
