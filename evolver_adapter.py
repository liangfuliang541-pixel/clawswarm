# evolver_adapter.py - Evolver Agent Adapter for ClawSwarm
#
# Integrates Evolver (OpenClaw-based agent) as a ClawSwarm node.
# Communication happens via OpenClaw's sessions_send / sessions_spawn
# tool calls from within the AI session context.
#
# Since Evolver runs as an OpenClaw agent, this adapter acts as a bridge:
#   - It stores tasks in a shared directory that Evolver can read
#   - It monitors Evolver's output directory for results
#   - Alternatively, it uses sessions_send to relay tasks directly
#
# Config:
#   evolver_agent_id:  OpenClaw agent ID (e.g. "evolver")
#   workspace_dir:     Evolver workspace path
#   poll_interval:     Result polling interval (seconds, default 2)

import asyncio
import json
import os
import time
import threading
from typing import Any, Dict, List, Optional
from pathlib import Path

from agent_adapter import AgentAdapter, register_adapter


@register_adapter("evolver")
class EvolverAdapter(AgentAdapter):
    """Adapter for Evolver Agent via OpenClaw sessions."""

    ADAPTER_TYPE = "evolver"

    CFG_AGENT_ID = "evolver_agent_id"
    CFG_WORKSPACE = "workspace_dir"
    CFG_POLL_INTERVAL = "poll_interval"

    def __init__(self, agent_id: str, config: dict = None):
        super().__init__(agent_id, config)
        self._workspace: Optional[str] = None
        self._task_dir: Optional[str] = None
        self._result_dir: Optional[str] = None
        self._poll_interval = self.config.get(self.CFG_POLL_INTERVAL, 2)
        self._sessions_send_fn = None  # Injected sessions_send callable

    # -- Lifecycle --

    def start(self) -> bool:
        workspace = self.config.get(self.CFG_WORKSPACE)
        if not workspace:
            # Try default evolver workspace
            home = os.path.expanduser("~")
            candidates = [
                os.path.join(home, ".openclaw", "workspace"),
                os.path.join(home, ".evomap"),
            ]
            for c in candidates:
                if os.path.isdir(c):
                    workspace = c
                    break

        if workspace and os.path.isdir(workspace):
            self._workspace = workspace
        else:
            # No filesystem workspace needed if using sessions_send
            pass

        self._task_dir = os.path.join(
            self._workspace or os.getcwd(), ".clawswarm_evolver_tasks"
        )
        self._result_dir = os.path.join(self._task_dir, "results")
        os.makedirs(self._result_dir, exist_ok=True)

        self._poll_interval = self.config.get(self.CFG_POLL_INTERVAL, 2)
        self._running = True
        self._started_at = time.time()
        return True

    def stop(self) -> None:
        self._running = False

    # -- Inject sessions_send --

    def set_sessions_send(self, fn):
        """Inject the sessions_send function for direct relay."""
        self._sessions_send_fn = fn

    # -- Task execution --

    async def execute(self, task: dict) -> dict:
        if not self._running:
            return self._make_result(
                task.get("id", "unknown"), "failed",
                error="Evolver adapter not running"
            )

        task_id = task.get("id", "unknown")
        prompt = task.get("prompt", task.get("description", ""))
        timeout = task.get("timeout_seconds", 300)

        if not prompt:
            return self._make_result(task_id, "failed", error="No prompt")

        # Strategy 1: Direct sessions_send (if injected)
        if self._sessions_send_fn:
            try:
                return await asyncio.wait_for(
                    self._execute_via_sessions(task_id, prompt),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                return self._make_result(task_id, "timeout",
                                         error=f"Evolver sessions timeout ({timeout}s)")
            except Exception as e:
                # Fall through to file-based strategy
                pass

        # Strategy 2: File-based (write task file, poll for result)
        try:
            return await asyncio.wait_for(
                self._execute_via_file(task_id, prompt, task),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            return self._make_result(task_id, "timeout",
                                     error=f"Evolver file poll timeout ({timeout}s)")
        except Exception as e:
            return self._make_result(task_id, "failed",
                                     error=f"Evolver error: {type(e).__name__}: {e}")

    # -- Health check --

    def health_check(self) -> dict:
        uptime = time.time() - self._started_at if self._started_at else 0
        return {
            "healthy": self._running,
            "agent_id": self.agent_id,
            "adapter_type": self.ADAPTER_TYPE,
            "uptime": uptime,
            "tasks_completed": self._task_count,
            "errors": self._error_count,
            "details": {
                "workspace": self._workspace,
                "task_dir": self._task_dir,
                "evolver_agent_id": self.config.get(self.CFG_AGENT_ID),
                "has_sessions_send": self._sessions_send_fn is not None,
            },
        }

    # -- Capabilities --

    @property
    def capabilities(self) -> List[str]:
        caps = self.config.get("capabilities", [])
        if not caps:
            caps = ["general", "code", "research", "evolve"]
        return caps

    # -- Internal: Execute via sessions_send --

    async def _execute_via_sessions(self, task_id: str, prompt: str) -> dict:
        """Send task to Evolver via sessions_send."""
        evolver_id = self.config.get(self.CFG_AGENT_ID, "evolver")
        if not self._sessions_send_fn:
            raise RuntimeError("sessions_send not injected")

        # Build a clear task message
        task_msg = (
            f"[ClawSwarm Task #{task_id}]\n"
            f"{prompt}\n\n"
            f"Reply with your result in JSON: {{\"status\": \"success\", \"output\": \"...\"}}"
        )

        # sessions_send is sync in tool context, wrap for async
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: self._sessions_send_fn(
                sessionKey=evolver_id,
                message=task_msg
            )
        )

        output = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
        return self._make_result(task_id, "done", output=output)

    # -- Internal: Execute via file polling --

    async def _execute_via_file(self, task_id: str, prompt: str, task: dict) -> dict:
        """Write task to file, poll for Evolver's result."""
        # Write task file
        task_file = os.path.join(self._task_dir, f"{task_id}.json")
        task_data = {
            "task_id": task_id,
            "prompt": prompt,
            "type": task.get("type", "general"),
            "created_at": time.time(),
        }
        with open(task_file, "w", encoding="utf-8") as f:
            json.dump(task_data, f, ensure_ascii=False, indent=2)

        # Poll for result
        result_file = os.path.join(self._result_dir, f"{task_id}.json")
        deadline = time.time() + task.get("timeout_seconds", 300)

        while time.time() < deadline:
            if os.path.exists(result_file):
                with open(result_file, "r", encoding="utf-8") as f:
                    result_data = json.load(f)
                # Cleanup
                try:
                    os.remove(task_file)
                    os.remove(result_file)
                except Exception:
                    pass
                return self._make_result(
                    task_id,
                    result_data.get("status", "done"),
                    output=result_data.get("output"),
                    error=result_data.get("error"),
                )
            await asyncio.sleep(self._poll_interval)

        # Timeout - cleanup task file
        try:
            os.remove(task_file)
        except Exception:
            pass
        raise TimeoutError("Evolver result not received in time")


if __name__ == "__main__":
    print("EvolverAdapter - OpenClaw Sessions Adapter")
    print("=" * 50)

    adapter = EvolverAdapter("test-evolver", config={
        "evolver_agent_id": "evolver",
    })

    print(f"Capabilities: {adapter.capabilities}")
    print(f"Starting...")
    ok = adapter.start()
    print(f"  Started: {ok}")

    if ok:
        health = adapter.health_check()
        print(f"  Health: {json.dumps(health, indent=2)}")
        adapter.stop()
        print("[STOP] Evolver adapter stopped")
