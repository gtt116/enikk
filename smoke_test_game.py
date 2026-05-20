"""Smoke test for game module — hermes AIAgent orchestrating NikkeRuntime tools."""
import time

import run_agent

from enikk.agent.prompts import AGENT_SYSTEM_PROMPT
from enikk.config import Config
from enikk.runtimes import NikkeRuntime

cfg = Config.from_yaml("config.yaml")
rt = NikkeRuntime(cfg)

# # ── 1. Process status ──────────────────────────────────────────────────

# print(f"[1] Game running: {rt.is_game_running}")
# print(f"    Launcher running: {rt.is_launcher_running}")

# # ── 2. Window discovery ────────────────────────────────────────────────

# game_hwnd = rt.find_game_window()
# print(f"[2] Game hwnd: {game_hwnd}")
# lh = rt.find_launcher_window()
# print(f"    Launcher hwnd: {lh}")

# # ── 3. Launch flow ─────────────────────────────────────────────────────

# if rt.is_game_running:
#     print("[3] Game already running, skipping launch")
# else:
#     print("[3] Testing launch() primitive...")
#     result = rt.launch()
#     print(f"    launch() → {result['status']}: {result.get('message', '')}")

#     if result["status"] == "launcher_ready":
#         print("    Launcher window is ready. You can analyze() the launcher UI.")
#     else:
#         print("[3] Launch failed — abort")
#         sys.exit(1)

#     # Manual step: user clicks "Start Game" in launcher
#     input("    >>> Click 'Start Game' in the launcher, then press Enter...")

#     # Test wait_for_game() primitive
#     print("    Testing wait_for_game() primitive...")
#     result = rt.wait_for_game()
#     print(f"    wait_for_game() → {result['status']}: {result.get('message', '')}")
#     game_hwnd = rt.find_game_window()

# if not game_hwnd:
#     print("No game window — abort")
#     sys.exit(1)

# # ── 4. Quick verify analyze ────────────────────────────────────────────

# print("[4] Quick verify analyze()...")
# state = rt.analyze()
# if "error" in state:
#     print(f"      FAIL: {state['error']}")
# else:
#     print(f"      OK: {state['width']}x{state['height']}, {len(state.get('ocr', []))} OCR items")

# ── 5. Register enikk tools → run AIAgent ──────────────────────────────

print("[5] Registering enikk tools in hermes registry...")
rt.register_tools()

mc = cfg.model
agent = run_agent.AIAgent(
    base_url=mc.base_url,
    api_key=mc.api_key,
    model=mc.default,
    max_tokens=mc.max_tokens,
    enabled_toolsets=["enikk"],
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

# ── 6. Cleanup ─────────────────────────────────────────────────────────

print("\n[6] Stopping game...")
stop_result = rt.stop()
print(f"    stop() → game_stopped={stop_result['game_stopped']}, launcher_stopped={stop_result['launcher_stopped']}")
time.sleep(1)
print(f"    Game still running: {rt.is_game_running}")

print("\nDone.")