# Enikk WebSocket 协议设计

> 2026-05-16 · 版本 2.1

## 设计原则

WebSocket 是 Enikk 的**唯一传输层**。参考 Hermes-Agent TUI Gateway 协议和 JSON-RPC 2.0。

- **游戏操作不走 WebSocket** — screenshot、click、launch 等是 daemon 内部接口，由 agent 工具直接调用，不暴露在 WS 协议中
- **WS 只承载 agent 生命周期控制和事件推送** — 与 hermes tui gateway 的 `session.*` / `slash.exec` 模式对齐
- `method` 标识操作，`id` 决定是否需要响应，`event` 是服务端主动推送

## 消息格式

### 请求（客户端 → 服务端）

```json
{
  "jsonrpc": "2.0",
  "id": "abc123",
  "method": "session.run",
  "params": {
    "session_id": "nikke",
    "prompt": "完成每日任务"
  }
}
```

### 成功响应（服务端 → 客户端）

```json
{
  "jsonrpc": "2.0",
  "id": "abc123",
  "result": {
    "run_id": "a1b2c3d4",
    "status": "accepted"
  }
}
```

### 错误响应

```json
{
  "jsonrpc": "2.0",
  "id": "abc123",
  "error": {
    "code": -32003,
    "message": "SESSION_BUSY"
  }
}
```

### 事件推送（服务端 → 客户端，无 id）

```json
{
  "jsonrpc": "2.0",
  "method": "event",
  "params": {
    "type": "session.step",
    "session_id": "nikke",
    "payload": {
      "action": "click",
      "target": "daily_button"
    }
  }
}
```

## 消息类型速查

| 特征 | req/res | event |
|------|---------|-------|
| `id` | ✅ 必填 | ❌ 无 |
| `session_id` | 在 `connect` 后绑定 | ✅ 必填 |
| 谁发 | 客户端发 req，服务端回 res | 仅服务端推送 |
| 是否响应 | 服务端必须响应 | 客户端不响应 |

## 连接握手

```
Client                              Server
  │                                   │
  │── TCP + WS Upgrade ─────────────▶│
  │◀── gateway.ready (event) ───────│  {"protocol":1}
  │                                   │
  │── connect (req) ────────────────▶│
  │◀── connect (res) ───────────────│
  │                                   │
  │   ... ready for RPC ...          │
```

```json
// 服务端先发 gateway.ready
{"jsonrpc":"2.0","method":"event","params":{"type":"gateway.ready","session_id":"","payload":{"protocol":1}}}

// 客户端发 connect
{"jsonrpc":"2.0","id":"1","method":"connect","params":{
  "role":"dashboard",
  "auth":{"token":"enikk_dashboard_token"},
  "client":{"id":"web-ui","version":"1.0"}
}}

// 服务端确认
{"jsonrpc":"2.0","id":"1","result":{"ok":true,"session_id":"conn_abc123","protocol":1,"tick_interval_ms":30000}}
```

## RPC 方法

与 hermes tui gateway 对齐：

| method | 对应 hermes | 方向 | pool? | 说明 |
|--------|------------|------|-------|------|
| `connect` | `session.create` | C→S | - | 连接认证 |
| `session.run` | `slash.exec` | C→S | pool | 触发 agent 异步执行 |
| `session.stop` | `session.interrupt` | C→S | - | 中断正在运行的 agent |
| `session.status` | `session.status` | C→S | - | 查询 agent 状态 |
| `session.list` | `agents.list` | C→S | - | 列出所有已注册游戏 agent |
| `ping` | - | C→S | - | 心跳保活 |

### 参数示例

```json
// session.run
{"jsonrpc":"2.0","id":"1","method":"session.run","params":{"session_id":"nikke","prompt":"完成每日任务"}}

// session.stop
{"jsonrpc":"2.0","id":"2","method":"session.stop","params":{"session_id":"nikke"}}

// session.status
{"jsonrpc":"2.0","id":"3","method":"session.status","params":{"session_id":"nikke"}}

// session.list
{"jsonrpc":"2.0","id":"4","method":"session.list","params":{}}
```

## 事件推送

### 事件类型

| event | 对应 hermes | 时机 | `session_id` | payload |
|-------|------------|------|-------------|---------|
| `gateway.ready` | `gateway.ready` | WS 连接建立 | `""` | `protocol` |
| `session.update` | `session.info` / `status.update` | agent 状态变化 | game_id | `status`, `run_id` |
| `session.step` | `tool.start` / `tool.complete` | agent 每步操作 | game_id | `action`, `target` |
| `session.error` | - | agent 报错 | game_id | `error`, `run_id` |
| `heartbeat` | `heartbeat` | 定时 30s | `""` | `ts` |

### 事件示例

```json
// Agent 开始工作
{"jsonrpc":"2.0","method":"event","params":{"type":"session.update","session_id":"nikke","payload":{"status":"busy","run_id":"a1b2"}}}

// 每步操作
{"jsonrpc":"2.0","method":"event","params":{"type":"session.step","session_id":"nikke","payload":{"action":"screenshot","summary":"日常任务 领取"}}}
{"jsonrpc":"2.0","method":"event","params":{"type":"session.step","session_id":"nikke","payload":{"action":"click","target":"daily_button","x":500,"y":320}}}

// 任务完成
{"jsonrpc":"2.0","method":"event","params":{"type":"session.update","session_id":"nikke","payload":{"status":"done","run_id":"a1b2","summary":"每日任务已完成"}}}
```

## 错误码

| code | message | 说明 |
|------|---------|------|
| `-32700` | Parse error | JSON 解析失败 |
| `-32600` | Invalid request | 请求格式错误 |
| `-32601` | Method not found | 未知方法 |
| `-32602` | Invalid params | 参数错误 |
| `-32000` | Handler error | 处理器内部异常 |
| `-32003` | SESSION_BUSY | Session 正在运行 |
| `-32004` | SESSION_NOT_FOUND | Session 不存在 |

## 连接生命周期

```
客户端                          服务端
  │                              │
  │── TCP + WS Upgrade ─────────▶│
  │◀── gateway.ready (event) ───│  session_id=""
  │── connect (req) ────────────▶│
  │◀── connect (res) ───────────│  session_id="conn_abc"
  │                              │
  │── session.run (req) ──────────▶│
  │◀── res {accepted} ──────────│  (立即返回)
  │◀── session.update (busy) ─────│  session_id="nikke"
  │◀── session.step (screenshot) ─│  session_id="nikke"
  │◀── session.step (click) ──────│  session_id="nikke"
  │◀── session.update (done) ─────│  session_id="nikke"
  │                              │
  │◀── heartbeat ───────────────│  session_id="" (每 30s)
  │                              │
  │── TCP disconnect ───────────▶│
```

## 心跳机制

- 服务端每 **30 秒** 推送一次 `heartbeat` 事件
- 客户端 **60 秒** 没收到任何消息就重连
- `connect` 响应中返回 `tick_interval_ms`

## 断线重连

```python
async def connect_with_retry(url: str):
    backoff = 1.0
    while True:
        try:
            async with websockets.connect(url) as ws:
                await handshake(ws)
                backoff = 1.0
                await event_loop(ws)
        except Exception:
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)
```

## 认证

Token 配置在 `config.yaml` 的 `dashboard.auth_token` 字段，在 `connect` 请求中传递。

```json
{"jsonrpc":"2.0","id":"1","method":"connect","params":{
  "role":"dashboard",
  "auth":{"token":"enikk_dashboard_token"},
  "client":{"id":"web-ui","version":"1.0"}
}}
```

## 架构说明

游戏操作（screenshot、click、launch、exit 等）**不走 WebSocket**。它们是 Daemon 的内部方法，由 agent 工具直接调用：

```
Dashboard ──WS──▶ Daemon.dispatch("session.run")
                      │
                      ▼
                  AgentManager._execute()
                      │
                      ▼
                  GameAgent.run()
                      │
                      ▼
                  Hermes AIAgent
                      │
                      ├── tool: screenshot ──▶ Daemon.analyze()        (内部调用)
                      ├── tool: click      ──▶ Daemon.action_click()   (内部调用)
                      └── tool: wait       ──▶ time.sleep()
                      │
                      ▼
                  callback ──▶ AgentManager._emit(event) ──▶ Dashboard
```

WebSocket 只承载 agent 生命周期（run/stop/status/list）和事件推送（update/step/error/heartbeat）。