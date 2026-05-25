"""Smoke test for NIKKE — Eternity session manager + hermes AIAgent."""
import logging
import time

from enikk.config import Config
from enikk.eternity import Eternity

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s %(message)s")

cfg = Config.from_yaml("config.yaml")
eternity = Eternity(cfg)
eternity.setup()

game = "nikke"
default_task = "Nikke: 打开游戏，登录到大厅，进入商店，领取免费商品"

# ── List sessions ─────────────────────────────────────────────────────

sessions = eternity.list_sessions(limit=10)
if sessions:
    print("\n    Recent sessions:")
    for s in sessions:
        title = s.get("title") or s.get("preview") or s.get("id", "")[:12]
        status = "active" if s.get("ended_at") is None else "ended"
        print(f"      [{s['id'][:12]}] {status}  {s.get('model','?')}  {title}")
else:
    print("\n    No existing sessions found.")

choice = input("\n    Enter session ID to resume, or 'n' for new session: ").strip()

if choice and choice.lower() != "n":
    session_id = choice
    print(f"\n    Resuming session {session_id}...")
    messages = eternity.get_session_messages(session_id)
    print(f"    {len(messages)} messages in session.")
    for msg in messages[-3:]:
        role = msg.get("role", "?")
        content = msg.get("content", "")
        if isinstance(content, list):
            content = content[0].get("text", "") if content else ""
        preview = content[:120].replace("\n", " ")
        print(f"      [{role}] {preview}")
    # TODO: resume conversation with existing history
    prompt = input("\n    Steer message (or Enter to skip): ").strip()
    if prompt:
        eternity.create_session(prompt, session_id=session_id)
else:
    prompt = input("\n    Task for agent (e.g. 'navigate to the lobby'): ").strip()
    if not prompt:
        prompt = default_task
        print(f"    Using default prompt: {prompt}")

    print(f"\n    Starting agent session (model={cfg.model.default})...\n")
    session_id = eternity.create_session(prompt)

result = eternity.wait_for_session(session_id)
response_text = result.get("final_response", "") if result else ""
print(f"\n    Agent response:\n{response_text}")

# ── Cleanup ─────────────────────────────────────────────────────────

print("\n[cleanup] Stopping game...")
controller = eternity._controller
if controller:
    stop_result = controller.stop(game=game)
    print(f"    stop() → game_stopped={stop_result['game_stopped']}, launcher_stopped={stop_result['launcher_stopped']}")
    time.sleep(1)
    print(f"    Game still running: {controller.is_game_running(game)}")

print("\nDone.")