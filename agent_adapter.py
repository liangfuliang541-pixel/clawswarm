# agent_adapter.py — ClawSwarm Agent Adapter Layer
#
# Abstract base + registry for heterogeneous agent integration.
# Each agent framework (OpenClaw, Hermes, Evolver) implements a subclass.
#
# Usage:
#   from agent_adapter import AgentAdapter, get_adapter
#   adapter = get_adapter('hermes', agent_id='hermes-01', config={...})
#   adapter.start()
#   result = await adapter.execute(task)
#   adapter.stop()

import abc
import time
import json
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional


class AgentAdapter(abc.ABC):
    """Abstract base class for agent adapters."""

    ADAPTER_TYPE: str = "base"

    def __init__(self, agent_id: str, config: dict = None):
        self.agent_id = agent_id
        self.config = config or {}
        self._running = False
        self._started_at = None
        self._task_count = 0
        self._error_count = 0

    # -- Lifecycle --

    @abc.abstractmethod
    def start(self) -> bool:
        """Start the agent. Return True on success."""
        ...

    @abc.abstractmethod
    def stop(self) -> None:
        """Stop the agent."""
        ...

    @property
    def running(self) -> bool:
        return self._running

    # -- Task execution --

    @abc.abstractmethod
    async def execute(self, task: dict) -> dict:
        """Execute a single task. Returns result dict."""
        ...

    # -- Health --

    @abc.abstractmethod
    def health_check(self) -> dict:
        """Return health status dict."""
        ...

    # -- Capabilities --

    @property
    def capabilities(self) -> List[str]:
        return self.config.get("capabilities", ["general"])

    def on_registered(self) -> None:
        """Callback after successful registration."""
        pass

    # -- Internal helpers --

    def _update_heartbeat(self):
        self._last_heartbeat = time.time()

    def _make_result(self, task_id: str, status: str,
                     output: Any = None, error: str = None,
                     extra: dict = None) -> dict:
        result = {
            "task_id": task_id,
            "status": status,
            "adapter_type": self.ADAPTER_TYPE,
            "executed_at": datetime.now().isoformat(),
        }
        if output is not None:
            result["output"] = output
        if error is not None:
            result["error"] = error
        if extra:
            result.update(extra)
        if status == "done":
            self._task_count += 1
        elif status == "failed":
            self._error_count += 1
        return result

    def __repr__(self):
        return f"<{self.__class__.__name__} agent_id={self.agent_id} running={self._running}>"


# -- Registry --

_ADAPTER_REGISTRY: Dict[str, type] = {}
_adapters_imported = False


def register_adapter(adapter_type: str):
    """Decorator: register an adapter class."""
    def decorator(cls):
        _ADAPTER_REGISTRY[adapter_type] = cls
        cls.ADAPTER_TYPE = adapter_type
        return cls
    return decorator


def get_adapter(adapter_type: str, agent_id: str, config: dict = None) -> AgentAdapter:
    """Factory: create adapter by type name."""
    _lazy_import_adapters()
    cls = _ADAPTER_REGISTRY.get(adapter_type)
    if cls is None:
        available = ", ".join(sorted(_ADAPTER_REGISTRY.keys())) or "(none)"
        raise ValueError(f"Unknown adapter type: '{adapter_type}'. Available: {available}")
    return cls(agent_id=agent_id, config=config)


def list_adapters() -> List[str]:
    """List all registered adapter types."""
    _lazy_import_adapters()
    return sorted(_ADAPTER_REGISTRY.keys())


def _lazy_import_adapters():
    """Lazy-import adapter subclasses to avoid circular deps."""
    global _adapters_imported
    if _adapters_imported:
        return
    _adapters_imported = True
    for mod_name in ("hermes_adapter", "evolver_adapter", "openclaw_adapter"):
        try:
            __import__(mod_name)
        except ImportError:
            pass
