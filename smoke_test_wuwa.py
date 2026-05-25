"""Smoke test for Wuthering Waves — Eternity session manager + hermes AIAgent."""
import logging
import time

from enikk.config import Config
from enikk.eternity import Eternity

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s %(message)s")

cfg = Config.from_yaml("config.yaml")
eternity = Eternity(cfg)
eternity.setup()

prompt = input("\n    Task for agent (e.g. 'navigate to the lobby'): ").strip()
if not prompt:
    prompt = "打开游戏，登录到大厅，进入商店，领取免费商品"
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
    stop_result = controller.stop(game="wutheringwave")
    print(f"    stop() → game_stopped={stop_result['game_stopped']}, launcher_stopped={stop_result['launcher_stopped']}")
    time.sleep(1)
    print(f"    Game still running: {controller.is_game_running('wutheringwave')}")

print("\nDone.")