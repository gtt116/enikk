"""Smoke test for Wuthering Waves — hermes AIAgent orchestrating GameController tools."""
import time

import run_agent

from enikk.agent.prompts import AGENT_SYSTEM_PROMPT
from enikk.config import Config
from enikk.game_controller import GameController

cfg = Config.from_yaml("config.yaml")
rt = GameController(cfg)

# ── Register game_controller tools → run AIAgent ──────────────────────

print("[1] Registering game_controller tools in hermes registry...")
rt.register_tools()

mc = cfg.model
agent = run_agent.AIAgent(
    base_url=mc.base_url,
    api_key=mc.api_key,
    model=mc.default,
    max_tokens=mc.max_tokens,
    enabled_toolsets=["game_controller"],
    quiet_mode=False,
    save_trajectories=False,
    max_iterations=500,
)

prompt = input("\n    Task for agent (e.g. 'navigate to the lobby'): ").strip()
if not prompt:
    prompt = "打开游戏，登录到大厅，进入商店，领取免费商品"
    print(f"    Using default prompt: {prompt}")

print(f"\n    Running agent (model={mc.default})...\n")
result = agent.run_conversation(prompt, system_message=AGENT_SYSTEM_PROMPT)
response_text = result.get("final_response", "")
print(f"\n    Agent response:\n{response_text}")

# ── Cleanup ─────────────────────────────────────────────────────────

print("\n[2] Stopping game...")
stop_result = rt.stop(game="wutheringwave")
print(f"    stop() → game_stopped={stop_result['game_stopped']}, launcher_stopped={stop_result['launcher_stopped']}")
time.sleep(1)
print(f"    Game still running: {rt.is_game_running('wutheringwave')}")

print("\nDone.")