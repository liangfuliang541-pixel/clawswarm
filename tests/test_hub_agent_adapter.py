"""Integration tests for HubAgent + adapter layer."""

import asyncio
import json
import os
import sys
import time
import threading
import socketserver
import http.server

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from networking import HubAgent, HubServer, _make_handler, HubClient
from agent_adapter import AgentAdapter, register_adapter, get_adapter


# ── Test adapter ────────────────────────────────────────────────────────────

@register_adapter("_test_hub")
class StubHubAdapter(AgentAdapter):
    ADAPTER_TYPE = "_test_hub"
    _executed = []

    def start(self) -> bool:
        self._running = True
        self._started_at = time.time()
        return True

    def stop(self) -> None:
        self._running = False

    async def execute(self, task: dict) -> dict:
        StubHubAdapter._executed.append(task)
        return self._make_result(
            task.get("id", task.get("task_id", "?")),
            "done",
            output=f"executed: {task.get('prompt', '')[:50]}",
        )

    def health_check(self) -> dict:
        return {"healthy": self._running, "adapter_type": self.ADAPTER_TYPE}


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _clear_executed():
    StubHubAdapter._executed.clear()
    yield


@pytest.fixture
def hub_and_server():
    """Start a real Hub HTTP server on a random port."""
    hub = HubServer()
    Handler = _make_handler(hub)
    # Find a free port
    with socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler) as srv:
        port = srv.server_address[1]
        srv.allow_reuse_address = True
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        yield hub, port
        srv.shutdown()


# ── Tests: HubAgent without adapter ────────────────────────────────────────

class TestHubAgentNoAdapter:

    def test_init_no_adapter(self):
        agent = HubAgent(hub_url="http://localhost:19999", agent_id="test-no-adapter")
        assert agent._adapter is None
        assert agent.capabilities == ["fetch", "exec", "python", "shell"]

    def test_execute_task_native(self):
        agent = HubAgent(hub_url="http://localhost:19999", agent_id="test")
        task = {"task_id": "t1", "type": "fetch", "prompt": "get http://example.com"}
        result = agent.execute_task(task)
        assert result["status"] == "executed"
        assert result["mode"] == "fetch"
        assert "example.com" in result["prompt"]


# ── Tests: HubAgent with adapter ──────────────────────────────────────────

class TestHubAgentWithAdapter:

    def test_init_with_adapter_type(self):
        agent = HubAgent(
            hub_url="http://localhost:19999",
            agent_id="test-adapter",
            adapter_type="_test_hub",
            adapter_config={"capabilities": ["code", "math"]},
        )
        assert agent._adapter is not None
        assert isinstance(agent._adapter, StubHubAdapter)
        assert agent.capabilities == ["code", "math"]

    def test_adapter_gets_agent_id(self):
        agent = HubAgent(
            hub_url="http://localhost:19999",
            agent_id="hermes-01",
            adapter_type="_test_hub",
        )
        assert agent._adapter.agent_id == "hermes-01"

    def test_execute_via_adapter(self):
        agent = HubAgent(
            hub_url="http://localhost:19999",
            agent_id="test-exec",
            adapter_type="_test_hub",
        )
        agent._adapter.start()
        task = {"id": "t-exec-1", "prompt": "solve 2+2"}
        result = agent.execute_task(task)
        assert result["status"] == "done"
        assert "solve 2+2" in result["output"]
        assert len(StubHubAdapter._executed) == 1

    def test_execute_via_adapter_multiple(self):
        agent = HubAgent(
            hub_url="http://localhost:19999",
            agent_id="test-multi",
            adapter_type="_test_hub",
        )
        agent._adapter.start()
        for i in range(5):
            result = agent.execute_task({"id": f"t-{i}", "prompt": f"task {i}"})
            assert result["status"] == "done"
        assert len(StubHubAdapter._executed) == 5

    def test_adapter_lifecycle_start_stop(self):
        agent = HubAgent(
            hub_url="http://localhost:19999",
            agent_id="test-lifecycle",
            adapter_type="_test_hub",
        )
        # adapter starts as part of agent.start(), but Hub is unreachable
        # so register fails. But adapter itself should start fine.
        assert agent._adapter.start() is True
        assert agent._adapter.running is True
        agent._adapter.stop()
        assert agent._adapter.running is False


# ── Tests: HubAgent + HubServer end-to-end ────────────────────────────────

class TestHubAgentE2E:

    def test_register_with_adapter_caps(self, hub_and_server):
        hub, port = hub_and_server
        agent = HubAgent(
            hub_url=f"http://127.0.0.1:{port}",
            agent_id="e2e-adapter",
            adapter_type="_test_hub",
            adapter_config={"capabilities": ["code", "evolve"]},
        )
        ok = agent.start()
        assert ok is True
        agents = hub.list_agents()
        assert len(agents) == 1
        assert agents[0]["agent_id"] == "e2e-adapter"
        assert sorted(agents[0]["capabilities"]) == ["code", "evolve"]
        agent.stop()

    def test_full_cycle_with_adapter(self, hub_and_server):
        hub, port = hub_and_server
        # Start agent with adapter
        agent = HubAgent(
            hub_url=f"http://127.0.0.1:{port}",
            agent_id="e2e-full",
            adapter_type="_test_hub",
            poll_interval=0.5,
        )
        ok = agent.start()
        assert ok is True

        # Submit a task via Hub
        task_id = hub.enqueue_task("e2e-full", {
            "prompt": "compute fibonacci(10)",
            "type": "python",
        })

        # Wait for agent to pick up and execute
        time.sleep(2)

        # Check result
        result = hub.get_result(task_id)
        assert result is not None
        assert result["status"] == "done"
        assert "fibonacci" in result["result"]["output"]

        agent.stop()

    def test_full_cycle_native(self, hub_and_server):
        hub, port = hub_and_server
        agent = HubAgent(
            hub_url=f"http://127.0.0.1:{port}",
            agent_id="e2e-native",
            poll_interval=0.5,
        )
        ok = agent.start()
        assert ok is True

        task_id = hub.enqueue_task("e2e-native", {
            "prompt": "hello world",
            "type": "fetch",
        })
        time.sleep(2)

        result = hub.get_result(task_id)
        assert result is not None
        assert result["status"] == "done"
        assert result["result"]["status"] == "executed"

        agent.stop()


# ── Tests: HubClient with adapter agent ───────────────────────────────────

class TestHubClientE2E:

    def test_client_submit_and_wait(self, hub_and_server):
        hub, port = hub_and_server
        agent = HubAgent(
            hub_url=f"http://127.0.0.1:{port}",
            agent_id="client-test",
            adapter_type="_test_hub",
            poll_interval=0.5,
        )
        agent.start()

        client = HubClient(f"http://127.0.0.1:{port}")
        agents = client.list_agents()
        assert any(a["agent_id"] == "client-test" for a in agents)

        tid = client.submit_task("client-test", {
            "prompt": "test from client",
            "type": "general",
        })
        result = client.wait_result(tid, timeout=10, poll_interval=0.5)
        assert result["status"] == "done"
        assert "test from client" in result["result"]["output"]

        agent.stop()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
