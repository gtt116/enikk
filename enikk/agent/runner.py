"""Hermes agent runner for Enikk — main session + post-review."""
import agent.trajectory as _trajectory
import logging
import os
import run_agent as hermes_agent
import tools.memory_tool
from datetime import datetime
from pathlib import Path

from .hermes_tools import register_tools
from .prompts import AGENT_SYSTEM_PROMPT, REVIEW_SYSTEM_PROMPT


class AgentRunner:
    def __init__(self, server_url: str, model: str, base_url: str, api_key: str):
        logging.getLogger().setLevel(logging.CRITICAL)

        os.environ["HERMES_HOME"] = "."
        print(f"server_url: {server_url}")
        register_tools(server_url)

        self.base_url = base_url
        self.api_key = api_key
        self.model = model

        self.agent = hermes_agent.AIAgent(
            base_url=base_url,
            api_key=api_key,
            model=model,
            enabled_toolsets=["enikk", "memory", "todo"],
            quiet_mode=False,
            save_trajectories=False,
            max_iterations=1000,
        )
        self._init_memory()

    def run(self, prompt: str):
        result = self.agent.run_conversation(prompt, system_message=AGENT_SYSTEM_PROMPT)
        response = result.get("final_response", "")
        print(response)
        self._save_trajectory(result, prompt)
        self._review_session(result)

    def _init_memory(self):
        self.agent._memory_store = tools.memory_tool.MemoryStore(memory_char_limit=100_000)
        self.agent._memory_store.load_from_disk()
        self.agent._memory_enabled = True
        self.agent._user_profile_enabled = True

    def _save_trajectory(self, result, prompt):
        try:
            traj_dir = Path("trajectories")
            traj_dir.mkdir(parents=True, exist_ok=True)
            traj_file = traj_dir / f"enikk_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.jsonl"
            messages = result.get("messages", [])
            trajectory = self.agent._convert_to_trajectory_format(messages, prompt, True)
            _trajectory.save_trajectory(trajectory, self.agent.model, True, filename=str(traj_file))
            print(f"[trajectory] Saved to {traj_file}")
        except Exception as e:
            print(f"[warn] Failed to save trajectory: {e}")

    def _review_session(self, result):
        try:
            print("\n--- Reviewing session ---")

            review_agent = hermes_agent.AIAgent(
                base_url=self.base_url,
                api_key=self.api_key,
                model=self.model,
                enabled_toolsets=["memory"],
                quiet_mode=False,
                save_trajectories=False,
                max_iterations=8,
            )
            review_agent._memory_store = self.agent._memory_store
            review_agent._memory_enabled = True
            review_agent._user_profile_enabled = True

            session_messages = result.get("messages", [])

            review_user_msg = (
                "Review this session. Update memory using the memory tool to add lessons, "
                "remove outdated entries, or consolidate duplicates. "
                "Keep only actionable insights that will make future sessions smoother. "
                "If nothing meaningful was learned, skip memory writes."
            )

            review_result = review_agent.run_conversation(
                review_user_msg,
                system_message=REVIEW_SYSTEM_PROMPT,
                conversation_history=session_messages,
            )
            review_text = review_result.get("final_response", "")
            if review_text:
                print(review_text)
        except Exception as e:
            print(f"[warn] Session review failed (non-fatal): {e}")
