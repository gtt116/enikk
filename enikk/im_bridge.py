"""Lightweight IM bridge — reuses hermes gateway platform adapters."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from .config import Config, enikk_home
from .eternity import Eternity
from .controller import extract_image_path
from .events import EVT_DELTA, EVT_TOOL_CALL, EVT_TOOL_RESULT, EVT_REASONING, EVT_STEP_CONTEXT, EVT_ERROR, EVT_SESSION

logger = logging.getLogger(__name__)


_STATE_FILE = enikk_home() / "im_state.json"


class IMBridge:
    """Bridge IM messages to Eternity sessions via hermes gateway adapters.

    Reuses hermes' platform adapters (Telegram, Discord, etc.) without
    reimplementing protocol logic. Each IM chat maps to one enikk session.
    """

    def __init__(self, config: Config, eternity: Eternity):
        self.config = config
        self.eternity = eternity
        self._adapter = None
        self._chat_sessions: dict[str, str] = {}  # chat_id → session_id
        self._active_streams: dict[str, asyncio.Task] = {}  # chat_id → stream task
        self._tool_notify: dict[str, bool] = {}  # chat_id → enabled
        self._image_notify: dict[str, bool] = {}  # chat_id → enabled
        self._progress_notify: dict[str, bool] = {}  # chat_id → enabled
        self._health_check_task: asyncio.Task | None = None
        self._load_state()

    def _load_state(self) -> None:
        try:
            if _STATE_FILE.exists():
                data = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
                self._chat_sessions = data.get("chat_sessions", {})
                self._tool_notify = data.get("tool_notify", {})
                self._image_notify = data.get("image_notify", {})
                self._progress_notify = data.get("progress_notify", {})
                logger.info("IM state loaded: %d sessions, %d tool_notify, %d image_notify, %d progress_notify",
                          len(self._chat_sessions), len(self._tool_notify), len(self._image_notify), len(self._progress_notify))
        except Exception as e:
            logger.warning("Failed to load IM state: %s", e)

    def _save_state(self) -> None:
        try:
            data = {
                "chat_sessions": self._chat_sessions,
                "tool_notify": self._tool_notify,
                "image_notify": self._image_notify,
                "progress_notify": self._progress_notify,
            }
            _STATE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            logger.debug("IM state saved")
        except Exception as e:
            logger.warning("Failed to save IM state: %s", e)

    async def start(self) -> None:
        """Initialize and connect the platform adapter."""
        im_cfg = self.config.im
        if not im_cfg:
            logger.info("IM bridge disabled")
            return

        active = im_cfg.active_platform
        if not active:
            logger.warning("IM bridge: no enabled platform configured")
            return

        platform_name, ps = active

        try:
            from gateway.config import Platform, PlatformConfig
        except ImportError:
            logger.error("hermes gateway not available — install hermes-agent")
            return

        pcfg = PlatformConfig(
            enabled=True,
            token=ps.token,
            extra=ps.extra,
        )

        platform = Platform(platform_name)
        self._adapter = self._create_adapter(platform, pcfg)
        if not self._adapter:
            logger.error("Failed to create adapter for %s", platform_name)
            return

        self._adapter.set_message_handler(self._handle_message)
        logger.info("Connecting IM adapter: %s", platform_name)

        connected = await self._adapter.connect()
        if connected:
            logger.info("IM bridge connected: %s", platform_name)
            self._start_health_check()
        else:
            logger.error("IM bridge connection failed")

    def _start_health_check(self) -> None:
        """Start background task that monitors and reconnects on disconnect."""
        if self._health_check_task and not self._health_check_task.done():
            return
        self._health_check_task = asyncio.create_task(self._health_check_loop())

    async def _health_check_loop(self) -> None:
        """Periodically check adapter connection, reconnect on disconnect."""
        interval = 60
        retry_delay = 30
        max_retries = 1024
        op_timeout = 30

        while self._adapter:
            await asyncio.sleep(interval)
            if not self._adapter:
                break

            if self._adapter.is_connected:
                continue

            logger.warning("IM bridge disconnected, attempting reconnect")
            for attempt in range(1, max_retries + 1):
                try:
                    await asyncio.wait_for(self._adapter.disconnect(), timeout=op_timeout)
                    connected = await asyncio.wait_for(self._adapter.connect(), timeout=op_timeout)
                    if connected:
                        logger.info("IM bridge reconnected (attempt %d)", attempt)
                        break
                    else:
                        logger.warning("IM bridge reconnect attempt %d failed", attempt)
                except asyncio.TimeoutError:
                    logger.warning("IM bridge reconnect attempt %d timed out", attempt)
                except Exception as e:
                    logger.warning("IM bridge reconnect attempt %d error: %s", attempt, e)

                if attempt < max_retries:
                    await asyncio.sleep(retry_delay)
            else:
                logger.error("IM bridge reconnect exhausted after %d attempts", max_retries)

    def _create_adapter(self, platform, pcfg):
        """Instantiate the appropriate hermes platform adapter."""
        from gateway.config import Platform

        if platform == Platform.DINGTALK:
            from gateway.platforms.dingtalk import DingTalkAdapter
            return DingTalkAdapter(pcfg)
        elif platform == Platform.QQBOT:
            from gateway.platforms.qqbot.adapter import QQAdapter
            return QQAdapter(pcfg)
        else:
            logger.warning("Unsupported IM platform: %s", platform.value)
            return None

    async def _handle_message(self, event) -> Optional[str]:
        """Route IM message to Eternity session, return response."""
        if not event or not event.text:
            return None

        chat_id = self._get_chat_id(event)
        if not chat_id:
            return None

        text = event.text.strip()
        logger.info("IM [%s] → %s", chat_id, text[:80])

        if text.startswith("/"):
            return await self._handle_command(text, chat_id)

        session_id = self._chat_sessions.get(chat_id)
        need_stream = False

        if session_id:
            was_running = self.eternity.is_running(session_id)
            success = self.eternity.steer_session(session_id, text)
            if not success:
                session_id = self.eternity.create_session(task=text)
                self._chat_sessions[chat_id] = session_id
                self._save_state()
                need_stream = True
            elif not was_running:
                # steer_session auto-loaded a new thread for the dead session
                need_stream = True
            else:
                # Steered running thread; ensure stream task exists
                active_task = self._active_streams.get(chat_id)
                if not active_task or active_task.done():
                    need_stream = True
        else:
            if self._adapter:
                await self._adapter.send(chat_id, "👋 新会话已创建。紧急停止请发送 /stop")
            session_id = self.eternity.create_session(task=text)
            self._chat_sessions[chat_id] = session_id
            self._save_state()
            need_stream = True

        if need_stream:
            stream_task = asyncio.create_task(self._stream_response(session_id, chat_id))
            self._active_streams[chat_id] = stream_task

        return None

    async def _handle_command(self, text: str, chat_id: str) -> Optional[str]:
        """Handle slash commands like /new, /stop, /help."""
        parts = text[1:].split(maxsplit=1)
        cmd = parts[0].lower()
        args = parts[1].strip() if len(parts) > 1 else ""
        logger.info("IM [%s] command: /%s", chat_id, cmd)

        if cmd == "new":
            # Stop the old agent thread before creating a new session
            old_session_id = self._chat_sessions.get(chat_id)
            if old_session_id:
                self.eternity.stop_session(old_session_id)
            active_task = self._active_streams.get(chat_id)
            if active_task and not active_task.done():
                active_task.cancel()
            if self._adapter:
                await self._adapter.send(chat_id, "👋 新会话已创建。紧急停止请发送 /stop")
            session_id = self.eternity.create_session(task=args or "New session")
            self._chat_sessions[chat_id] = session_id
            self._save_state()
            logger.info("IM [%s] /new session: %s", chat_id, session_id)
            stream_task = asyncio.create_task(self._stream_response(session_id, chat_id))
            self._active_streams[chat_id] = stream_task
            return None

        elif cmd == "stop":
            stop_session_id = self._chat_sessions.get(chat_id)
            stopped = False
            if stop_session_id:
                if self.eternity.stop_session(stop_session_id):
                    stopped = True

            # Also cancel active stream task if any (handles case where thread died but task is hanging)
            active_task = self._active_streams.get(chat_id)
            if active_task and not active_task.done():
                active_task.cancel()
                stopped = True

            if stopped:
                return f"🛑 已停止会话: {stop_session_id or 'unknown'}"
            else:
                return "⚠️ 当前没有运行中的会话"

        elif cmd == "tools":
            current = self._tool_notify.get(chat_id, True)
            self._tool_notify[chat_id] = not current
            self._save_state()
            state = "🔔 已开启" if not current else "🔕 已关闭"
            return f"🔧 工具调用通知: {state}"

        elif cmd == "images":
            current = self._image_notify.get(chat_id, True)
            self._image_notify[chat_id] = not current
            self._save_state()
            state = "🔔 已开启" if not current else "🔕 已关闭"
            return f"📷 图片发送: {state}"

        elif cmd == "progress":
            current = self._progress_notify.get(chat_id, True)
            self._progress_notify[chat_id] = not current
            self._save_state()
            state = "🔔 已开启" if not current else "🔕 已关闭"
            return f"📊 进度回显: {state}"

        elif cmd == "help":
            return (
                "/new [提示词] - 新建会话\n"
                "/stop - 停止当前会话\n"
                "/tools - 工具通知开关\n"
                "/images - 图片发送开关\n"
                "/progress - 进度回显开关"
            )

        else:
            return f"⚠️ 未知命令: /{cmd}\n\n可用: /new, /stop, /tools, /images, /progress, /help"

    def _get_chat_id(self, event) -> Optional[str]:
        """Extract chat identifier from message event (DM only)."""
        source = getattr(event, "source", None)
        if not source:
            return None
        chat_type = getattr(source, "chat_type", None)
        if chat_type != "dm":
            logger.info("IM bridge: ignoring non-DM message (type=%s)", chat_type)
            return None
        return getattr(source, "chat_id", None)

    async def _stream_response(self, session_id: str, chat_id: str) -> None:
        """Stream agent response to IM platform.

        Accumulates deltas in a buffer, flushes as complete messages at event
        boundaries (tool_call, tool_result, session) — matching how
        js/app.js groups parts. Avoids stream-edit and message splitting.
        """
        adapter = self._adapter
        if not adapter:
            return

        buffer: list[str] = []
        delta_sent = False

        async def flush():
            nonlocal buffer, delta_sent
            text = "".join(buffer).strip()
            buffer.clear()
            if text:
                await adapter.send(chat_id, text)
                delta_sent = True

        try:
            async for event in self.eternity.get_session_stream(session_id):
                event_type = event.get("event")
                data = event.get("data", {})

                if event_type == EVT_DELTA:
                    text = data.get("text", "")
                    if text:
                        logger.debug("IM [%s] delta: %r", chat_id, text)
                        if self._progress_notify.get(chat_id, True):
                            buffer.append(text)

                elif event_type == EVT_TOOL_CALL:
                    name = data.get("name", "")
                    args = data.get("args", {})
                    logger.debug("IM [%s] tool_call: %s", chat_id, name)
                    await flush()
                    if self._tool_notify.get(chat_id, True):
                        args_str = str(args)[:80] if args else ""
                        hint = f"`{name}({args_str})`" if args_str else f"`{name}()`"
                        msg = f"🔧 {hint}"
                        if len(msg) > 200:
                            msg = msg[:197] + "..."
                        await adapter.send(chat_id, msg)

                elif event_type == EVT_TOOL_RESULT:
                    name = data.get("name", "")
                    logger.debug("IM [%s] tool_result: %s", chat_id, name)
                    if self._image_notify.get(chat_id, True):
                        img_path = extract_image_path(data.get("result"))
                        if img_path:
                            logger.debug("IM [%s] sending image: %s", chat_id, img_path)
                            try:
                                await adapter.send_image(chat_id, img_path)
                            except Exception:
                                logger.warning("IM [%s] send_image failed for %s", chat_id, img_path)

                elif event_type == EVT_REASONING:
                    logger.debug("IM [%s] reasoning: %r", chat_id, data.get("text", "")[:50])

                elif event_type == EVT_STEP_CONTEXT:
                    logger.debug("IM [%s] step_context: %s", chat_id, data)

                elif event_type == EVT_ERROR:
                    msg = data.get("message", "Unknown error")
                    logger.warning("IM [%s] error: %s", chat_id, msg)
                    await flush()
                    await adapter.send(chat_id, f"❌ {msg}")

                elif event_type == EVT_SESSION:
                    status = data.get("status")
                    if status in ("completed", "stopped", "error"):
                        await flush()
                        final_response = data.get("final_response")
                        if final_response and not delta_sent and status == "completed":
                            await adapter.send(chat_id, final_response)
                        logger.info("IM [%s] session %s", chat_id, status)
                        break

            # Flush any remaining buffer after stream ends
            await flush()

        except asyncio.CancelledError:
            logger.debug("IM [%s] stream cancelled", chat_id)
        except Exception:
            logger.warning("IM [%s] stream failed", chat_id, exc_info=True)
        finally:
            current_task = asyncio.current_task()
            if self._active_streams.get(chat_id) is current_task:
                self._active_streams.pop(chat_id, None)

    async def stop(self) -> None:
        """Disconnect the adapter and stop health check."""
        if self._health_check_task and not self._health_check_task.done():
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass
        if self._adapter:
            logger.info("Stopping IM bridge")
            try:
                await asyncio.wait_for(self._adapter.disconnect(), timeout=10)
            except asyncio.TimeoutError:
                logger.warning("IM bridge disconnect timed out")
            except Exception as e:
                logger.warning("IM bridge disconnect error: %s", e)

    # ── Public status API ────────────────────────────────────────────────

    def is_enabled(self) -> bool:
        """Check if IM bridge has an active platform configured."""
        return self._adapter is not None

    def is_connected(self) -> bool:
        """Check if the IM adapter is currently connected."""
        if not self._adapter:
            return False
        return getattr(self._adapter, 'is_connected', False)

    def get_platform_name(self) -> str | None:
        """Get the name of the active IM platform."""
        active = self.config.im.active_platform
        return active[0] if active else None
