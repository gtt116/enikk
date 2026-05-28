"""Lightweight IM bridge — reuses hermes gateway platform adapters."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from .config import Config
from .eternity import Eternity
from .controller import IMAGE_PATH_KEY, SOM_IMAGE_PATH_KEY

logger = logging.getLogger(__name__)


def _extract_image_path(result) -> Optional[str]:
    """Extract local image path from a tool result (dict or JSON string)."""
    obj = None
    if isinstance(result, dict):
        obj = result
    elif isinstance(result, str):
        try:
            obj = json.loads(result)
        except (ValueError, TypeError):
            pass
    if obj and isinstance(obj, dict):
        path = obj.get(SOM_IMAGE_PATH_KEY) or obj.get(IMAGE_PATH_KEY)
        if path:
            return path
    return None


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
        else:
            logger.error("IM bridge connection failed")

    def _create_adapter(self, platform, pcfg):
        """Instantiate the appropriate hermes platform adapter."""
        from gateway.config import Platform

        if platform == Platform.TELEGRAM:
            from gateway.platforms.telegram import TelegramAdapter
            return TelegramAdapter(pcfg)
        elif platform == Platform.DISCORD:
            from gateway.platforms.discord import DiscordAdapter
            return DiscordAdapter(pcfg)
        elif platform == Platform.SLACK:
            from gateway.platforms.slack import SlackAdapter
            return SlackAdapter(pcfg)
        elif platform == Platform.DINGTALK:
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
            session_id = self.eternity.create_session(task=text)
            self._chat_sessions[chat_id] = session_id
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
            session_id = self.eternity.create_session(task=args or "New session")
            self._chat_sessions[chat_id] = session_id
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
            state = "🔔 已开启" if not current else "🔕 已关闭"
            return f"🔧 工具调用通知: {state}"

        elif cmd == "help":
            return (
                "🤖 **Enikk 助手**\n\n"
                "🆕 /new [提示词] - 新建会话\n"
                "🛑 /stop - 停止当前会话\n"
                "🔧 /tools - 切换工具调用通知\n"
                "ℹ️ /help - 显示帮助"
            )

        else:
            return f"⚠️ 未知命令: /{cmd}\n\n可用: /new, /stop, /tools, /help"

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
        """Stream agent response to IM platform via GatewayStreamConsumer."""
        from gateway.stream_consumer import GatewayStreamConsumer, StreamConsumerConfig

        adapter = self._adapter

        consumer = GatewayStreamConsumer(
            adapter=adapter,
            chat_id=chat_id,
            config=StreamConsumerConfig(chat_type="dm", cursor=""),
        )
        consumer_task = asyncio.create_task(consumer.run())

        try:
            async for event in self.eternity.get_session_stream(session_id):
                event_type = event.get("event")
                data = event.get("data", {})

                if event_type == "delta":
                    text = data.get("text", "")
                    if text:
                        logger.debug("IM [%s] delta: %r", chat_id, text)
                        consumer.on_delta(text)

                elif event_type == "tool_call":
                    if self._tool_notify.get(chat_id, True):
                        name = data.get("name", "")
                        args = data.get("args", {})
                        args_str = str(args)[:80] if args else ""
                        hint = f"[{name}({args_str})]" if args_str else f"[{name}()]"
                        consumer.on_delta(None)
                        consumer.on_delta("🔧 " + hint + "\n")
                    logger.debug("IM [%s] tool_call: %s", chat_id, data.get("name", ""))

                elif event_type == "tool_result":
                    name = data.get("name", "")
                    logger.debug("IM [%s] tool_result: %s", chat_id, name)
                    img_path = _extract_image_path(data.get("result"))
                    if img_path and adapter:
                        logger.debug("IM [%s] sending image: %s", chat_id, img_path)
                        try:
                            await adapter.send_image(chat_id, img_path)
                        except Exception:
                            logger.warning("IM [%s] send_image failed for %s", chat_id, img_path)

                elif event_type == "session":
                    status = data.get("status")
                    if status in ("completed", "stopped", "error"):
                        logger.info("IM [%s] session %s", chat_id, status)
                        break
        finally:
            consumer.finish()
            try:
                await consumer_task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.warning("IM [%s] stream consumer failed", chat_id, exc_info=True)
            # Safe cleanup: only remove if this task is still the tracked one
            current_task = asyncio.current_task()
            if self._active_streams.get(chat_id) is current_task:
                self._active_streams.pop(chat_id, None)

        logger.info("IM [%s] stream finished (sent=%s)", chat_id, consumer.already_sent)

    async def stop(self) -> None:
        """Disconnect the adapter."""
        if self._adapter:
            logger.info("Stopping IM bridge")
            await self._adapter.disconnect()
