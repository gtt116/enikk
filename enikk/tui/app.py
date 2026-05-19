"""Enikk TUI — Textual dashboard for the WebSocket daemon."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime

import websockets
import websockets.exceptions
from websockets import ClientConnection
from textual import on
from textual.app import App, ComposeResult
from textual.widgets import Footer, Header, Input, TextArea


class EnikkTui(App):
    """Terminal dashboard connected to the Enikk WebSocket daemon."""

    CSS = """
    #event-log {
        height: 1fr;
        border: solid $surface-lighten-1;
        padding: 0 1;
    }

    #prompt-input {
        width: 100%;
    }
    """

    BINDINGS = [
        ("ctrl+q", "quit", "Quit"),
        ("ctrl+s", "send_prompt", "Send"),
        ("ctrl+r", "refresh", "Refresh"),
    ]

    def __init__(self, server: str = "127.0.0.1", port: int = 18932):
        super().__init__()
        self._server = server
        self._port = port
        self._ws: ClientConnection | None = None
        self._connected = False
        self._log_text = ""

    def compose(self) -> ComposeResult:
        yield Header()
        yield TextArea(id="event-log", read_only=True, soft_wrap=True, show_line_numbers=False)
        yield Input(placeholder="Send prompt to agent...", id="prompt-input", disabled=True)
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = "Disconnected"
        self.query_one("#event-log", TextArea).can_focus = False
        self.run_worker(self._ws_connect(), exclusive=True)

    def _append_log(self, line: str) -> None:
        self._log_text += line + "\n"
        log = self.query_one("#event-log", TextArea)
        log.load_text(self._log_text)
        log.scroll_end(animate=False)

    async def _ws_connect(self) -> None:
        inp = self.query_one("#prompt-input", Input)
        url = f"ws://{self._server}:{self._port}"
        delay = 1
        attempt = 0

        while True:
            attempt += 1
            try:
                await self._connect_once(url, inp)
                delay = 1
                attempt = 0
            except asyncio.CancelledError:
                break
            except OSError:
                pass  # logged in _connect_once
            except websockets.exceptions.ConnectionClosed:
                pass  # logged in _connect_once

            if attempt > 1:
                self._append_log(f"  Reconnecting in {delay}s... (attempt {attempt})")
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30)

    async def _connect_once(self, url: str, inp: Input) -> None:
        try:
            async with websockets.connect(url, max_size=10 * 1024 * 1024) as ws:
                self._ws = ws
                self._connected = True
                self.sub_title = "Connected"
                inp.disabled = False
                inp.focus()

                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    self._handle_message(msg)
        except OSError:
            self._append_log("  Connection failed")
            raise
        except websockets.exceptions.ConnectionClosed as e:
            self._append_log(f"  Disconnected: {e}")
            raise
        finally:
            self._ws = None
            self._connected = False
            self.sub_title = "Disconnected"
            inp.disabled = True

    def _handle_message(self, msg: dict) -> None:
        ts = datetime.now().strftime("%H:%M:%S")

        if msg.get("method") == "event":
            params = msg.get("params", {})
            event_type = params.get("type", "unknown")
            payload = params.get("payload", {})
            self._append_log(f"  {ts} [{event_type}] {json.dumps(payload, ensure_ascii=False)}")
            return

        if "id" in msg:
            rid = msg["id"]
            if "result" in msg:
                result = msg["result"]
                if isinstance(result, dict):
                    summary = result.get("status", result.get("ok", json.dumps(result, ensure_ascii=False)[:80]))
                else:
                    summary = str(result)[:80]
                self._append_log(f"  {ts} [ok #{rid}] {summary}")
            elif "error" in msg:
                self._append_log(f"  {ts} [err #{rid}] {msg['error'].get('message', '')}")
            return

        event_type = msg.get("type", "")
        if event_type:
            rest = {k: v for k, v in msg.items() if k != 'type'}
            self._append_log(f"  {ts} [{event_type}] {json.dumps(rest, ensure_ascii=False)[:120]}")
            return

        self._append_log(f"  {ts} {json.dumps(msg, ensure_ascii=False)[:120]}")

    @on(Input.Submitted, "#prompt-input")
    async def _on_send(self, event: Input.Submitted) -> None:
        prompt = event.value.strip()
        if not prompt or not self._ws:
            return

        inp = self.query_one("#prompt-input", Input)
        inp.clear()

        req = {
            "jsonrpc": "2.0",
            "id": str(hash(prompt) % 10000),
            "method": "session.run",
            "params": {"session_id": "nikke", "prompt": prompt},
        }
        try:
            await self._ws.send(json.dumps(req))
            self._append_log(f"▶ {prompt[:100]}")
        except Exception as e:
            self._append_log(f"Send failed: {e}")

    def action_refresh(self) -> None:
        if self._ws and self._connected:
            self.run_worker(self._do_refresh())

    async def _do_refresh(self) -> None:
        if self._ws is None:
            return
        try:
            await self._ws.send(json.dumps({"jsonrpc": "2.0", "id": "r", "method": "session.list"}))
        except Exception:
            pass