"""Test suite for agent_adapter layer."""

import asyncio
import json
import os
import sys
import time
import tempfile
import threading

import pytest
import pytest_asyncio

# Ensure clawswarm root is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_adapter import (
    AgentAdapter, register_adapter, get_adapter,
    list_adapters, _ADAPTER_REGISTRY, _adapters_imported
)
from hermes_adapter import HermesAdapter
from evolver_adapter import EvolverAdapter
from openclaw_adapter import OpenClawAdapter


# ── Fixtures ────────────────────────────────────────────────────────────────

class DummyAdapter(AgentAdapter):
    """Minimal concrete adapter for testing the base class."""

    ADAPTER_TYPE = "dummy"

    def __init__(self, agent_id="dummy", config=None, **kw):
        super().__init__(agent_id, config)
        self._should_fail_start = kw.get("fail_start", False)
        self._executed_tasks = []
        self._on_exec = kw.get("on_exec")

    def start(self) -> bool:
        if self._should_fail_start:
            return False
        self._running = True
        self._started_at = time.time()
        return True

    def stop(self) -> None:
        self._running = False

    async def execute(self, task: dict) -> dict:
        task_id = task.get("id", "unknown")
        if self._on_exec:
            self._on_exec(task)
        self._executed_tasks.append(task)
        return self._make_result(task_id, "done", output="dummy-result")

    def health_check(self) -> dict:
        return {
            "healthy": self._running,
            "agent_id": self.agent_id,
            "adapter_type": self.ADAPTER_TYPE,
        }


@pytest.fixture
def dummy():
    return DummyAdapter("test-dummy", config={"key": "val"})


# ── AgentAdapter base ──────────────────────────────────────────────────────

class TestAgentAdapter:

    def test_init_defaults(self, dummy):
        assert dummy.agent_id == "test-dummy"
        assert dummy.config == {"key": "val"}
        assert dummy.running is False
        assert dummy._task_count == 0
        assert dummy._error_count == 0

    def test_start_stop(self, dummy):
        assert dummy.start() is True
        assert dummy.running is True
        dummy.stop()
        assert dummy.running is False

    def test_start_failure(self):
        a = DummyAdapter("fail", fail_start=True)
        assert a.start() is False
        assert a.running is False

    def test_capabilities_from_config(self):
        a = DummyAdapter("cap", config={"capabilities": ["fetch", "exec"]})
        assert sorted(a.capabilities) == ["exec", "fetch"]

    def test_capabilities_default(self):
        a = DummyAdapter("def")
        assert a.capabilities == ["general"]

    def test_make_result_done(self, dummy):
        dummy.start()
        r = dummy._make_result("t1", "done", output="hello")
        assert r["task_id"] == "t1"
        assert r["status"] == "done"
        assert r["output"] == "hello"
        assert r["adapter_type"] == "dummy"
        assert "executed_at" in r
        assert dummy._task_count == 1

    def test_make_result_failed(self, dummy):
        r = dummy._make_result("t2", "failed", error="boom")
        assert r["status"] == "failed"
        assert r["error"] == "boom"
        assert dummy._error_count == 1

    def test_make_result_extra(self, dummy):
        r = dummy._make_result("t3", "done", output="x", extra={"meta": 42})
        assert r["meta"] == 42

    def test_repr(self, dummy):
        dummy._running = True
        text = repr(dummy)
        assert "DummyAdapter" in text
        assert "test-dummy" in text
        assert "running=True" in text

    def test_on_registered(self, dummy):
        # Should not raise
        dummy.on_registered()

    @pytest.mark.asyncio
    async def test_execute(self, dummy):
        dummy.start()
        r = await dummy.execute({"id": "e1", "prompt": "do stuff"})
        assert r["status"] == "done"
        assert r["output"] == "dummy-result"
        assert len(dummy._executed_tasks) == 1

    def test_health_check(self, dummy):
        dummy.start()
        h = dummy.health_check()
        assert h["healthy"] is True
        assert h["agent_id"] == "test-dummy"


# ── Registry ────────────────────────────────────────────────────────────────

class TestRegistry:

    def test_register_decorator(self):
        @register_adapter("_test_temp")
        class Tmp(AgentAdapter):
            def start(self): return True
            def stop(self): pass
            async def execute(self, task): return {}
            def health_check(self): return {}

        assert "_test_temp" in _ADAPTER_REGISTRY
        assert _ADAPTER_REGISTRY["_test_temp"] is Tmp
        assert Tmp.ADAPTER_TYPE == "_test_temp"
        # Cleanup
        del _ADAPTER_REGISTRY["_test_temp"]

    def test_list_adapters(self):
        adapters = list_adapters()
        assert "hermes" in adapters
        assert "evolver" in adapters
        assert "openclaw" in adapters

    def test_get_adapter_hermes(self):
        a = get_adapter("hermes", "h1", config={"model": "test"})
        assert isinstance(a, HermesAdapter)
        assert a.agent_id == "h1"

    def test_get_adapter_evolver(self):
        a = get_adapter("evolver", "e1")
        assert isinstance(a, EvolverAdapter)

    def test_get_adapter_openclaw(self):
        a = get_adapter("openclaw", "o1", config={"hub_url": "http://localhost:18080"})
        assert isinstance(a, OpenClawAdapter)

    def test_get_adapter_unknown(self):
        with pytest.raises(ValueError, match="Unknown adapter type.*nosuch"):
            get_adapter("nosuch", "x")


# ── HermesAdapter ──────────────────────────────────────────────────────────

class TestHermesAdapter:

    def test_init(self):
        h = HermesAdapter("hermes-01", config={
            "hermes_bin": "hermes",
            "model": "qwen2.5:72b",
            "max_tokens": 4096,
        })
        assert h.agent_id == "hermes-01"
        assert h.config["model"] == "qwen2.5:72b"
        assert h._initialized is False
        assert h._process is None

    def test_capabilities(self):
        h = HermesAdapter("h1")
        assert "general" in h.capabilities
        assert "code" in h.capabilities

    def test_capabilities_custom(self):
        h = HermesAdapter("h1", config={"capabilities": ["math"]})
        assert h.capabilities == ["math"]

    def test_start_no_binary(self):
        h = HermesAdapter("h1", config={"hermes_bin": "/nonexistent/hermes"})
        ok = h.start()
        assert ok is False

    def test_health_not_running(self):
        h = HermesAdapter("h1")
        health = h.health_check()
        assert health["healthy"] is False
        assert health["adapter_type"] == "hermes"

    @pytest.mark.asyncio
    async def test_execute_not_running(self):
        h = HermesAdapter("h1")
        r = await h.execute({"id": "t1", "prompt": "hello"})
        assert r["status"] == "failed"
        assert "not running" in r["error"]

    @pytest.mark.asyncio
    async def test_execute_no_prompt(self):
        h = HermesAdapter("h1")
        h._running = True
        h._initialized = True
        r = await h.execute({"id": "t2"})
        assert r["status"] == "failed"
        assert "No prompt" in r["error"]

    def test_extract_output_string(self):
        assert HermesAdapter._extract_output("hello") == "hello"

    def test_extract_output_list(self):
        result_data = {"content": [
            {"type": "text", "text": "line1"},
            {"type": "text", "text": "line2"},
        ]}
        result = HermesAdapter._extract_output(result_data)
        assert result == "line1\nline2"

    def test_extract_output_result_block(self):
        result_data = {"content": [
            {"type": "result", "text": "final answer"},
        ]}
        assert HermesAdapter._extract_output(result_data) == "final answer"

    def test_extract_output_mixed(self):
        result_data = {"content": [
            {"type": "text", "text": "thinking..."},
            {"type": "result", "text": "42"},
        ]}
        result = HermesAdapter._extract_output(result_data)
        assert "42" in result


# ── EvolverAdapter ─────────────────────────────────────────────────────────

class TestEvolverAdapter:

    def test_init(self):
        e = EvolverAdapter("evo-01", config={
            "evolver_agent_id": "evolver",
            "poll_interval": 1,
        })
        assert e.agent_id == "evo-01"
        assert e._poll_interval == 1

    def test_capabilities(self):
        e = EvolverAdapter("e1")
        assert "evolve" in e.capabilities

    def test_start(self):
        e = EvolverAdapter("e1")
        ok = e.start()
        assert ok is True
        assert e._running is True
        e.stop()

    def test_health_running(self):
        e = EvolverAdapter("e1")
        e.start()
        h = e.health_check()
        assert h["healthy"] is True
        assert h["adapter_type"] == "evolver"
        e.stop()

    @pytest.mark.asyncio
    async def test_execute_not_running(self):
        e = EvolverAdapter("e1")
        r = await e.execute({"id": "t1", "prompt": "hi"})
        assert r["status"] == "failed"

    @pytest.mark.asyncio
    async def test_execute_no_prompt(self):
        e = EvolverAdapter("e1")
        e.start()
        r = await e.execute({"id": "t2"})
        assert r["status"] == "failed"
        assert "No prompt" in r["error"]
        e.stop()

    @pytest.mark.asyncio
    async def test_execute_via_file_timeout(self):
        """File-based execution with no writer should timeout fast."""
        e = EvolverAdapter("e1", config={"poll_interval": 0.1})
        e.start()
        r = await e.execute({
            "id": "t-timeout",
            "prompt": "wait forever",
            "timeout_seconds": 1,
        })
        assert r["status"] == "timeout"
        e.stop()

    def test_set_sessions_send(self):
        e = EvolverAdapter("e1")
        fn = lambda **kw: None
        e.set_sessions_send(fn)
        assert e._sessions_send_fn is fn

    def test_health_shows_sessions_send(self):
        e = EvolverAdapter("e1")
        e.start()
        e.set_sessions_send(lambda **kw: None)
        h = e.health_check()
        assert h["details"]["has_sessions_send"] is True
        e.stop()


# ── OpenClawAdapter ────────────────────────────────────────────────────────

class TestOpenClawAdapter:

    def test_init(self):
        o = OpenClawAdapter("oc-01", config={
            "hub_url": "http://192.168.1.100:18080",
            "capabilities": ["fetch", "exec"],
        })
        assert o.agent_id == "oc-01"
        assert o._hub_url == "http://192.168.1.100:18080"

    def test_capabilities(self):
        o = OpenClawAdapter("o1", config={"capabilities": ["python", "general"]})
        assert sorted(o.capabilities) == ["general", "python"]

    def test_start_no_hub(self):
        """Start fails if Hub is not reachable."""
        o = OpenClawAdapter("o1", config={"hub_url": "http://127.0.0.1:19999"})
        ok = o.start()
        assert ok is False

    def test_health_not_running(self):
        o = OpenClawAdapter("o1")
        h = o.health_check()
        assert h["healthy"] is False

    @pytest.mark.asyncio
    async def test_execute(self):
        o = OpenClawAdapter("o1")
        r = await o.execute({"id": "t1", "prompt": "hi"})
        assert r["status"] == "done"
        assert "acknowledged" in r["output"]


# ── Integration: full adapter lifecycle ────────────────────────────────────

class TestAdapterLifecycle:

    @pytest.mark.asyncio
    async def test_full_cycle_with_dummy(self):
        """Register → create → start → execute → health → stop."""
        @register_adapter("_lifecycle_test")
        class LifecycleAdapter(AgentAdapter):
            ADAPTER_TYPE = "_lifecycle_test"
            def start(self):
                self._running = True
                self._started_at = time.time()
                return True
            def stop(self):
                self._running = False
            async def execute(self, task):
                return self._make_result(task["id"], "done", output="ok")
            def health_check(self):
                return {"healthy": self._running, "tasks": self._task_count}

        a = get_adapter("_lifecycle_test", "lc-1")
        assert a.start() is True

        r = await a.execute({"id": "lc-001", "prompt": "test"})
        assert r["status"] == "done"
        assert r["output"] == "ok"

        h = a.health_check()
        assert h["healthy"] is True
        assert h["tasks"] == 1

        a.stop()
        assert a.running is False

        # Cleanup
        del _ADAPTER_REGISTRY["_lifecycle_test"]

    def test_all_adapters_have_required_methods(self):
        """Every registered adapter must implement the 4 abstract methods."""
        for name, cls in _ADAPTER_REGISTRY.items():
            assert callable(getattr(cls, "start", None)), f"{name}.start missing"
            assert callable(getattr(cls, "stop", None)), f"{name}.stop missing"
            assert callable(getattr(cls, "execute", None)), f"{name}.execute missing"
            assert callable(getattr(cls, "health_check", None)), f"{name}.health_check missing"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
