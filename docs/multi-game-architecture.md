# Enikk WebSocket Gateway 架构设计

> 2026-05-16 · 版本 2.1

## 设计原则

- **WebSocket 是唯一传输层** — 去掉 HTTP REST，所有外部通信走 WebSocket
- **游戏操作不走 WebSocket** — screenshot、click、launch 等是 daemon 内部方法，agent 工具直接调用
- **WS 只承载 agent 生命周期 + 事件推送** — 与 hermes tui gateway 的 `session.*` / `slash.exec` 模式对齐
- **Daemon 实现 Dispatcher** — dispatch 在 thread pool 执行，event loop 不阻塞
- **Agent 线程内聚在 Daemon** — Agent 不再作为独立 CLI 进程，而是在 daemon 线程池中执行
- **事件广播由 AgentManager 负责** — 直接持有 WS 连接集合，不经过 transport 抽象层

---

## 拓扑结构

```
┌──────────────────────────────────────────────────────────┐
│  Frontend (Vue.js Web Dashboard)                         │
│  CLI (enikk agent "prompt" — 薄客户端)                    │
└────────────┬─────────────────────────────────────────────┘
             │ WebSocket
             │ ws://127.0.0.1:18932
             │ JSON-RPC (newline-delimited)
             ▼
┌──────────────────────────────────────────────────────────┐
│  Application (application.py)                             │
│                                                           │
│  ┌────────────────────────────────────────────────────┐  │
│  │  WsServer (ws_server.py)                           │  │
│  │  - accept 连接，收发 JSON-RPC 帧                     │  │
│  │  - 读循环 → asyncio.to_thread(dispatcher.dispatch)  │  │
│  └──────────────────┬─────────────────────────────────┘  │
│                     │                                     │
│  ┌──────────────────▼─────────────────────────────────┐  │
│  │  Daemon (daemon.py) — 实现 Dispatcher               │  │
│  │                                                    │  │
│  │  ┌─────────────────┐  ┌─────────────────────────┐  │  │
│  │  │ Game Core       │  │  AgentManager           │  │  │
│  │  │ - capture       │  │  _agents[game_id]: dict │  │  │
│  │  │ - input         │  │  run(game_id, prompt)   │  │  │
│  │  │ - analyzer      │  │       → rid             │  │  │
│  │  │ - ui_parser     │  │  stop(game_id)          │  │  │
│  │  │ - process       │  │  status(game_id) → dict │  │  │
│  │  └─────────────────┘  │  _ws_clients: set[WS]   │  │  │
│  │                       │  _pool: ThreadPool(4)   │  │  │
│  │                       └─────────────────────────┘  │  │
│  │                                                    │  │
│  │  dispatch(req) → dict                              │  │
│  │  RPC: connect, session.run/stop/status/list        │  │
│  └────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
```

### 对比：旧 vs 新

| | 旧架构 | 新架构 |
|---|---|---|
| 传输层 | FastAPI HTTP REST | WebSocket JSON-RPC |
| Agent 位置 | 独立 CLI 进程 | Daemon 线程池内 |
| Agent 生命周期 | CLI 退出即死 | Daemon 管理，持久运行 |
| 事件推送 | SSE stream | WebSocket event push |
| 多客户端 | 无状态 HTTP | 有状态 WS 连接 |
| I/O 抽象 | 无 | Dispatcher Protocol |

---

## 模块职责

| 模块 | 文件 | 职责 |
|------|------|------|
| WsServer | `enikk/ws_server.py` | Dispatcher Protocol + WebSocket 服务端 |
| Daemon | `enikk/daemon.py` | 游戏核心 + dispatch 路由 + Agent 生命周期管理 |
| AgentManager | `enikk/agent/manager.py` | Agent 创建/运行/中断，线程池调度，事件广播 |
| Application | `enikk/application.py` | 组装 Daemon + WsServer，启动 asyncio loop |
| CLI | `enikk/cli.py` | 薄客户端：连 WS，发 session.run，打印事件 |
| GameAgent | `enikk/agent/base.py` | 游戏 agent 抽象基类（不变） |
| Game Tools | `enikk/agent/tools/` | 通用工具（不变） |
| Games | `enikk/games/` | 游戏注册 + 专属 agent（不变） |

---

## 核心实现

### 1. WsServer + Dispatcher Protocol

```python
# enikk/ws_server.py
import asyncio
import json
import logging
from typing import Protocol, runtime_checkable
import websockets
from websockets import ServerConnection

logger = logging.getLogger(__name__)

@runtime_checkable
class Dispatcher(Protocol):
    """Interface for JSON-RPC request handlers."""
    def dispatch(self, req: dict) -> dict:
        """Handle one JSON-RPC request and return a response."""

class WsServer:
    def __init__(self, dispatcher: Dispatcher, host="127.0.0.1", port=18932):
        self._dispatcher = dispatcher
        self._host = host
        self._port = port

    async def serve_forever(self):
        async with websockets.serve(self._handle, self._host, self._port,
                                     max_size=10*1024*1024,
                                     ping_interval=30, ping_timeout=10) as server:
            self._server = server
            await server.serve_forever()

    async def _handle(self, ws: ServerConnection):
        ws.send(json.dumps({"jsonrpc":"2.0","method":"event",
            "params":{"type":"gateway.ready","session_id":"","payload":{"protocol":1}}}))

        try:
            async for raw in ws:
                line = raw.strip() if isinstance(raw, str) else ""
                if not line:
                    continue
                try:
                    req = json.loads(line)
                except json.JSONDecodeError:
                    ws.send(json.dumps({"jsonrpc":"2.0",
                        "error":{"code":-32700,"message":"Parse error"},"id":None}))
                    continue

                resp = await asyncio.to_thread(self._dispatcher.dispatch, req)
                if resp is not None:
                    ws.send(json.dumps(resp))
        except websockets.ConnectionClosed:
            logger.debug("Connection closed: %s", ws.remote_address)
        finally:
            logger.info("Client disconnected: %s", ws.remote_address)

    def shutdown(self):
        if self._server:
            self._server.get_loop().call_soon_threadsafe(self._server.close)
```

### 2. Daemon — 实现 Dispatcher

```python
# enikk/daemon.py
from .ws_server import Dispatcher
from .agent.manager import AgentManager

_rpc_registry: dict[str, callable] = {}

def rpc(method: str):
    """Decorator: register a method as JSON-RPC handler."""
    def decorator(fn):
        _rpc_registry[method] = fn
        return fn
    return decorator

class Daemon:
    def __init__(self, config: Config):
        self.config = config
        # ── Game core ──
        self.proc_mgr = process.ProcessManager(...)
        self.capture = capture.CaptureMethod(...)
        self.input = input_mod.Input(...)
        self.ui_parser = UIParser(...)

        # ── Agent ──
        self.agent_mgr = AgentManager(self)

    # ── Dispatcher.dispatch ──────────────────────────

    def dispatch(self, req: dict) -> dict:
        rid = req.get("id")
        method = req.get("method", "")
        params = req.get("params", {}) or {}

        fn = _rpc_registry.get(method)
        if fn is None:
            return {"jsonrpc": "2.0", "id": rid,
                    "error": {"code": -32601, "message": f"unknown method: {method}"}}

        try:
            result = fn(self, rid, params)
            return {"jsonrpc": "2.0", "id": rid, "result": result}
        except Exception as exc:
            return {"jsonrpc": "2.0", "id": rid,
                    "error": {"code": -32000, "message": str(exc)}}

    # ── Handlers ─────────────────────────────────────

    @rpc("ping")
    def _ping(self, rid, params):
        return "pong"

    @rpc("session.run")
    def _session_run(self, rid, params):
        run_id = self.agent_mgr.run(params["session_id"], params["prompt"])
        return {"run_id": run_id, "status": "accepted"}

    @rpc("session.stop")
    def _session_stop(self, rid, params):
        self.agent_mgr.stop(params["session_id"])
        return {"status": "stopped"}

    @rpc("session.status")
    def _session_status(self, rid, params):
        return self.agent_mgr.status(params["session_id"])

    @rpc("session.list")
    def _session_list(self, rid, params):
        return {"agents": self.agent_mgr.list_agents()}
```

### 3. AgentManager

```python
# enikk/agent/manager.py
import threading
import uuid
from enikk.games import get_agent

class AgentManager:
    def __init__(self, daemon: "Daemon"):
        self._daemon = daemon
        self._agents: dict[str, dict] = {}
        self._lock = threading.Lock()

    def run(self, game_id: str, prompt: str) -> str:
        """Start agent in pool. Returns run_id immediately."""
        run_id = uuid.uuid4().hex[:8]
        agent = get_agent(game_id=game_id, daemon=self._daemon)

        with self._lock:
            self._agents[game_id] = {
                "agent": agent, "run_id": run_id, "status": "busy",
            }

        self._daemon._pool.submit(
            lambda: self._execute(game_id, agent, prompt, run_id))
        return run_id

    def _execute(self, game_id, agent, prompt, run_id):
        try:
            self._emit("session.update", {"game": game_id, "status": "busy", "run_id": run_id})
            result = agent.run(prompt)
            self._emit("session.update", {"game": game_id, "status": "done", "run_id": run_id, "summary": result})
        except Exception as exc:
            self._emit("session.error", {"game": game_id, "run_id": run_id, "error": str(exc)})
        finally:
            with self._lock:
                if game_id in self._agents:
                    self._agents[game_id]["status"] = "idle"

    def stop(self, game_id: str):
        with self._lock:
            entry = self._agents.get(game_id)
        if entry:
            entry["agent"].interrupt("user requested stop")
            self._emit("session.update", {"game": game_id, "status": "idle"})

    def status(self, game_id: str) -> dict:
        entry = self._agents.get(game_id)
        if not entry:
            return {"game": game_id, "status": "idle", "run_id": None}
        return {"game": game_id, "status": entry["status"], "run_id": entry.get("run_id")}

    def list_agents(self) -> list:
        return [self.status(gid) for gid in self._agents]

    def _emit(self, event_type: str, payload: dict):
        """Broadcast event to all connected WebSocket clients."""
        frame = json.dumps({
            "jsonrpc": "2.0", "method": "event",
            "params": {"type": event_type, "payload": payload},
        })
        # WsServer exposes connected clients for broadcast
        for ws in self._daemon.ws_server.clients:
            try:
                ws.send(frame)
            except Exception:
                pass
```

### 4. Agent Callback → Event 链路

Agent 执行过程中通过 `AgentManager._emit()` 将事件广播到所有 WebSocket 客户端:

```
Hermes tool_start_callback → AgentManager._emit("session.step", ...)
    → ws.send(event_frame)  (for each connected client)
    → WebSocket → Dashboard 实时渲染
```

### 5. Application 入口

```python
# enikk/application.py
import asyncio
from .config import Config
from .daemon import Daemon
from .ws_server import WsServer

class Application:
    def __init__(self, config: Config):
        self.config = config
        self.daemon: Daemon | None = None
        self.ws_server: WsServer | None = None

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._start())
        except KeyboardInterrupt:
            logger.info("Interrupted, shutting down...")
        finally:
            loop.run_until_complete(self._shutdown())
            loop.close()

    async def _start(self):
        self.daemon = Daemon(self.config)
        self.daemon.init(auto_launch=False)

        ws_port = getattr(self.config, "ws_port", 18932)
        self.ws_server = WsServer(
            dispatcher=self.daemon,
            host=self.config.host,
            port=ws_port,
        )

        logger.info(f"Enikk started — ws://{self.config.host}:{ws_port}")
        await self.ws_server.serve_forever()

    async def _shutdown(self):
        if self.ws_server:
            self.ws_server.shutdown()
        if self.daemon:
            self.daemon.stop()
```

### 6. CLI 薄客户端

```python
# enikk/cli.py
def cmd_agent(args):
    import asyncio, websockets, json

    async def _run():
        async with websockets.connect(f"ws://{args.server}/") as ws:
            raw = await ws.recv()
            ready = json.loads(raw)  # gateway.ready

            await ws.send(json.dumps({
                "jsonrpc": "2.0", "id": "1",
                "method": "session.run",
                "params": {"game": args.game, "prompt": args.prompt},
            }))

            async for raw in ws:
                msg = json.loads(raw)
                if msg.get("method") == "event":
                    _print_event(msg["params"])
                elif msg.get("id") == "1":
                    print(f"Result: {msg.get('result')}")
                    break

    asyncio.run(_run())
```

---

## WebSocket 协议

客户端与服务端之间使用 **JSON-RPC 2.0** 消息帧，每行一个 JSON 对象。

### 消息类型

| type | id | 方向 | 说明 |
|------|-----|------|------|
| `req` (隐式) | ✅ 有 | C→S | 请求，服务端必须响应 |
| `res` (隐式) | ✅ 匹配 | S→C | 成功/错误响应 |
| `event` | ❌ 无 | S→C | 主动推送（agent 进度、游戏状态变化） |

### 连接握手

```
Client                    Server
  │                         │
  │── WS Connect ──────────▶│
  │◀── gateway.ready ──────│  (event, protocol version)
  │── connect (req) ───────▶│
  │◀── connect (res) ──────│
  │                         │
  │── session.run (req) ─────▶│
  │◀── res {accepted} ─────│
  │◀── session.update (event)│  (busy)
  │◀── session.step (event)  │  (click "daily_button")
  │◀── session.step (event)  │  (screenshot)
  │◀── session.update (event)│  (done)
```

### RPC 方法列表

| method | 方向 | 说明 |
|--------|------|------|
| `connect` | C→S | 连接认证 |
| `session.run` | C→S | 启动 agent（线程池执行） |
| `session.stop` | C→S | 中断 agent |
| `session.status` | C→S | 查询 agent 状态 |
| `session.list` | C→S | 列出所有 agent |

游戏操作（screenshot、click、launch、exit 等）**不是 RPC 方法**，它们是 Daemon 的内部方法，由 agent 工具直接调用。

### 事件类型

| event | 时机 | payload |
|-------|------|---------|
| `gateway.ready` | WS 连接建立 | `protocol` |
| `session.update` | agent 状态变化 | `game`, `status`, `run_id` |
| `session.step` | agent 每步操作 | `game`, `action`, `target` |
| `session.error` | agent 报错 | `game`, `error` |
| `heartbeat` | 定时心跳 (30s) | `ts` |

---

## 数据流示例

```
Dashboard 用户点击 "完成每日任务"
  │
  ├─ WS send: {"method":"session.run","params":{"game":"nikke","prompt":"完成每日任务"},"id":"1"}
  │
  ├─ Daemon.dispatch("session.run")
  │   └─ AgentManager.run("nikke", "完成每日任务")
  │       └─ pool.submit(_execute)
  │
  ├─ WS recv: {"method":"event","params":{"type":"session.update","payload":{"game":"nikke","status":"busy"}}}
  ├─ WS recv: {"method":"event","params":{"type":"session.step","payload":{"game":"nikke","action":"screenshot"}}}
  ├─ WS recv: {"method":"event","params":{"type":"session.step","payload":{"game":"nikke","action":"click","target":"daily_button"}}}
  ├─ ...
  ├─ WS recv: {"method":"event","params":{"type":"session.update","payload":{"game":"nikke","status":"done","summary":"每日任务已完成"}}}
  │
  └─ WS recv: {"id":"1","result":{"run_id":"abc123","status":"accepted"}}
```

---

## 实现步骤

### Phase 1: WsServer + Dispatcher Protocol

| # | 动作 | 产出 |
|---|------|------|
| 1 | 创建 `enikk/ws_server.py` | `Dispatcher` Protocol, `WsServer` |
| 2 | 验证 | 用 `websockets` 客户端连上，收到 `gateway.ready` 事件 |

### Phase 2: Daemon dispatch 骨架

| # | 动作 | 产出 |
|---|------|------|
| 3 | Daemon 实现 `Dispatcher`，添加 `_methods` + `dispatch()` | dispatch 路由机制 |
| 4 | 注册 `connect` handler | 连接认证，返回 `session_id` |
| 5 | 注册 `session.run/stop/status/list` handlers | 桩实现 |
| 6 | 验证 | WS 客户端发 `session.list` → 返回游戏列表 |

### Phase 3: AgentManager + 执行链路

| # | 动作 | 产出 |
|---|------|------|
| 7 | 创建 `enikk/agent/manager.py` | `AgentManager`：run/stop/status/list，pool 执行 |
| 8 | Daemon 持有 `self.agent_mgr = AgentManager(self)` | 生命周期管理 |
| 9 | `session.run` 对接 `agent_mgr.run()` | pool 执行，立即返回 run_id |
| 10 | `session.stop` 对接 `agent_mgr.stop()` | 中断运行中的 agent |
| 11 | `_execute` 中通过 `AgentManager._emit()` 广播事件 | 实时推送到所有 WS 客户端 |
| 12 | 验证 | 发 session.run → agent 执行 → 事件推送到客户端 |

### Phase 4: Agent 工具去 HTTP 化

| # | 动作 | 产出 |
|---|------|------|
| 13 | 修改 screenshot/click 工具构造函数注入 daemon | 直接调 `daemon.analyze()` / `daemon.action_click()` |
| 14 | 删除 `enikk/agent/hermes_tools.py` | 旧的 HTTP-based tool registry |
| 15 | 验证 | agent tool 调用不再经过 HTTP |

### Phase 5: 应用组装 + CLI 迁移

| # | 动作 | 产出 |
|---|------|------|
| 16 | 重写 `enikk/application.py` | 组装 Daemon + WsServer |
| 17 | 重写 `enikk/cli.py` `cmd_agent` | 薄 WS 客户端 |
| 18 | 删除 `enikk/server.py` | FastAPI HTTP 完全移除 |
| 19 | 端到端验证 | daemon 启动 → CLI 连 WS → agent 执行 → 事件打印 |

### Phase 6: 前端对接

| # | 动作 | 产出 |
|---|------|------|
| 20 | Dashboard `connect` + `gateway.ready` 握手 | 连接建立 |
| 21 | `session.list` → 游戏选择器 | 下拉菜单 |
| 22 | `session.run` + 事件流渲染 | 实时 agent.step 进度卡片 |
| 23 | `session.stop` 按钮 | 中断 agent |
| 24 | `session.status` 轮询/事件 | idle/busy 状态指示 |