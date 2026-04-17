# openclaw_adapter.py - OpenClaw Native Agent Adapter for ClawSwarm
#
# Adapts the existing OpenClaw HubAgent (HTTP polling) into the
# AgentAdapter interface. This is the default adapter for native
# OpenClaw agents that poll the Hub via HTTP.
#
# Since native OpenClaw agents already use HubAgent.poll() + HubAgent.submit_result(),
# this adapter is a thin wrapper that delegates to networking.py's HubClient.

import asyncio
import json
import time
from typing import Any, Dict, List, Optional
from datetime import datetime

from agent_adapter import AgentAdapter, register_adapter


@register_adapter("openclaw")
class OpenClawAdapter(AgentAdapter):
    """Adapter for native OpenClaw agents (Hub HTTP polling)."""

    ADAPTER_TYPE = "openclaw"

    CFG_HUB_URL = "hub_url"
    CFG_CAPABILITIES = "capabilities"

    def __init__(self, agent_id: str, config: dict = None):
        super().__init__(agent_id, config)
        self._hub_url = self.config.get(self.CFG_HUB_URL)
        self._registered = False
        self._poll_loop_task = None
        self._on_task_callback = None

    # -- Lifecycle --

    def start(self) -> bool:
        hub_url = self.config.get(self.CFG_HUB_URL)
        if not hub_url:
            # Try default
            hub_url = "http://127.0.0.1:18080"

        self._hub_url = hub_url

        # Register with Hub
        try:
            self._register_with_hub()
            self._registered = True
        except Exception as e:
            self._stderr_lines = getattr(self, '_stderr_lines', [])
            self._stderr_lines.append(f"Hub registration failed: {e}")
            return False

        self._running = True
        self._started_at = time.time()
        self.on_registered()
        return True

    def stop(self) -> None:
        self._running = False
        if self._poll_loop_task:
            self._poll_loop_task.cancel()
            self._poll_loop_task = None
        self._registered = False

    # -- Task execution --

    async def execute(self, task: dict) -> dict:
        """Execute a task. For native agents, this is a pass-through since
        the Hub handles task distribution via polling."""
        task_id = task.get("id", "unknown")
        # Native agents poll from Hub; this method is called when Hub pushes
        # a task directly (rare) or for testing.
        return self._make_result(
            task_id, "done",
            output="[OpenClaw native agent - task acknowledged]"
        )

    # -- Health check --

    def health_check(self) -> dict:
        uptime = time.time() - self._started_at if self._started_at else 0
        hub_ok = False
        if self._hub_url:
            try:
                import urllib.request
                req = urllib.request.Request(f"{self._hub_url}/hub/status",
                                            headers={"User-Agent": "ClawSwarm"})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    hub_ok = resp.status == 200
            except Exception:
                pass

        return {
            "healthy": self._running and hub_ok,
            "agent_id": self.agent_id,
            "adapter_type": self.ADAPTER_TYPE,
            "uptime": uptime,
            "tasks_completed": self._task_count,
            "errors": self._error_count,
            "registered": self._registered,
            "details": {
                "hub_url": self._hub_url,
                "hub_reachable": hub_ok,
            },
        }

    # -- Capabilities --

    @property
    def capabilities(self) -> List[str]:
        return self.config.get(self.CFG_CAPABILITIES, ["general"])

    # -- Internal: Hub registration --

    def _register_with_hub(self):
        """Register this agent with the Hub."""
        import urllib.request
        caps = self.capabilities
        payload = json.dumps({
            "agent_id": self.agent_id,
            "capabilities": caps,
            "adapter_type": self.ADAPTER_TYPE,
            "timestamp": datetime.now().isoformat(),
        }).encode("utf-8")

        req = urllib.request.Request(
            f"{self._hub_url}/hub/register",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "ClawSwarm/0.10",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            if not result.get("ok"):
                raise RuntimeError(f"Hub rejected registration: {result}")


if __name__ == "__main__":
    print("OpenClawAdapter - Native OpenClaw Agent Adapter")
    print("=" * 50)

    adapter = OpenClawAdapter("local-node-01", config={
        "hub_url": "http://127.0.0.1:18080",
        "capabilities": ["fetch", "exec", "python", "general"],
    })

    print(f"Capabilities: {adapter.capabilities}")
    print(f"Starting...")
    ok = adapter.start()
    print(f"  Started: {ok}")

    if ok:
        health = adapter.health_check()
        print(f"  Health: {json.dumps(health, indent=2)}")
        adapter.stop()
        print("[STOP] OpenClaw adapter stopped")
