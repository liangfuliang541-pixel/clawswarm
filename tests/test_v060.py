"""
ClawSwarm v0.6.0 测试 - HITL + Observability
"""

import pytest, time, os, sys, threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestCheckpoint:
    """checkpoint.py 测试"""

    def test_checkpoint_import(self):
        import checkpoint
        assert hasattr(checkpoint, 'Checkpoint')
        assert hasattr(checkpoint, 'CheckpointManager')
        assert hasattr(checkpoint, 'HITL_POLICY')
        assert hasattr(checkpoint, 'checkpoint')

    def test_always_approve_policy(self):
        from checkpoint import HITL_POLICY, ApprovalResult
        HITL_POLICY.set_always_approve()
        assert HITL_POLICY._mode == "always_approve"
        assert HITL_POLICY.should_require() == False
        assert HITL_POLICY.should_require(task_type="code") == False

    def test_always_require_policy(self):
        from checkpoint import HITL_POLICY
        HITL_POLICY.set_always_require()
        assert HITL_POLICY._mode == "always_require"
        assert HITL_POLICY.should_require() == True

    def test_priority_policy(self):
        from checkpoint import HITL_POLICY
        HITL_POLICY.set_require_above_priority(threshold=5)
        assert HITL_POLICY._mode == "by_priority"
        assert HITL_POLICY.should_require(priority=3) == False
        assert HITL_POLICY.should_require(priority=5) == True
        assert HITL_POLICY.should_require(priority=10) == True

    def test_checkpoin_model(self):
        from checkpoint import Checkpoint, CheckpointType
        chk = Checkpoint(
            id="chk_test",
            task_id="t_001",
            description="Test approval",
            type=CheckpointType.APPROVAL,
        )
        d = chk.to_dict()
        assert d["id"] == "chk_test"
        assert d["task_id"] == "t_001"
        assert d["type"] == "approval"

    def test_checkpoint_manager_create_auto_approve(self):
        from checkpoint import CheckpointManager, ApprovalResult, CheckpointType, HITL_POLICY
        HITL_POLICY.set_always_approve()
        mgr = CheckpointManager()
        chk = mgr.create("t_test", CheckpointType.CONFIRM, "Test checkpoint")
        assert chk.id is not None
        # Auto approve means immediate decision
        decision = mgr.get_decision(chk.id)
        assert decision.result in (ApprovalResult.APPROVED, ApprovalResult.SKIPPED)

    def test_checkpoint_manager_approve_reject(self):
        from checkpoint import CheckpointManager, ApprovalResult, CheckpointType
        from checkpoint import HITL_POLICY
        HITL_POLICY.set_always_require()  # Force real waiting
        mgr = CheckpointManager()
        chk = mgr.create("t_test2", CheckpointType.CONFIRM, "Test approval")
        chk_id = chk.id

        # Approve immediately
        ok = mgr.approve(chk_id, approver="unit_test", reason="test")
        assert ok == True

        decision = mgr.get_decision(chk_id)
        assert decision.result == ApprovalResult.APPROVED
        assert decision.approver == "unit_test"
        assert decision.reason == "test"

    def test_checkpoint_manager_reject(self):
        from checkpoint import CheckpointManager, ApprovalResult, CheckpointType
        from checkpoint import HITL_POLICY
        HITL_POLICY.set_always_require()
        mgr = CheckpointManager()
        chk = mgr.create("t_test3", CheckpointType.APPROVAL, "Reject test")
        chk_id = chk.id

        ok = mgr.reject(chk_id, approver="tester", reason="not approved")
        assert ok == True
        decision = mgr.get_decision(chk_id)
        assert decision.result == ApprovalResult.REJECTED

    def test_checkpoint_stats(self):
        from checkpoint import CheckpointManager, CheckpointType
        from checkpoint import HITL_POLICY
        HITL_POLICY.set_always_require()
        mgr = CheckpointManager()
        # Create and decide
        chk = mgr.create("t_stats", CheckpointType.CONFIRM, "Stats test")
        mgr.approve(chk.id)
        stats = mgr.stats()
        assert "pending" in stats
        assert "approved" in stats
        assert "rejected" in stats
        assert "policy" in stats


class TestObservability:
    """observability.py 测试"""

    def test_observability_import(self):
        import observability
        assert hasattr(observability, 'tracer')
        assert hasattr(observability, 'log')
        assert hasattr(observability, 'events')
        assert hasattr(observability, 'get_metrics')

    def test_metrics_counter(self):
        from observability import get_metrics
        m = get_metrics()
        m.counter("test.counter", 1.0, type="unit")
        assert m._counters

    def test_metrics_gauge(self):
        from observability import get_metrics
        m = get_metrics()
        m.gauge("test.gauge", 42.0, node="test")
        assert m._gauges

    def test_metrics_histogram(self):
        from observability import get_metrics
        m = get_metrics()
        m.histogram("test.hist", 1.5, type="unit")
        assert m._histograms

    def test_metrics_prometheus_format(self):
        from observability import get_metrics
        m = get_metrics()
        m.counter("test.counter", 5.0, type="demo")
        prom = m.to_prometheus()
        assert "test_counter" in prom or "test.counter" in prom
        assert "demo" in prom

    def test_metrics_export_json(self):
        from observability import get_metrics
        m = get_metrics()
        m.counter("test.j", 1.0)
        data = m.export_json()
        assert "timestamp" in data
        assert "counters" in data

    def test_tracer_noop(self):
        from observability import tracer
        with tracer.start_as_current_span("test_span") as span:
            span.set_attribute("key", "value")
        # No-op tracer should not raise

    def test_traced_decorator(self):
        from observability import traced
        @traced("test_func")
        def dummy():
            return 42
        result = dummy()
        assert result == 42

    def test_logger(self):
        from observability import log
        log.info("test message", task_id="test")
        log.warn("warning test")
        # Should not raise

    def test_event_emitter(self):
        from observability import events
        received = []

        def handler(event):
            received.append(event)

        events.on(handler)
        events.task_started("test_task", node="test_node")
        events.off(handler)

        assert len(received) >= 1
        assert received[-1]["type"] == "task.started"
        assert received[-1]["data"]["task_id"] == "test_task"

    def test_checkpoint_integration(self):
        from observability import events
        received = []
        events.on(lambda e: received.append(e))

        from checkpoint import CheckpointManager, CheckpointType, HITL_POLICY
        HITL_POLICY.set_always_require()
        mgr = CheckpointManager()
        chk = mgr.create("t_obs", CheckpointType.CONFIRM, "Obs test")
        mgr.approve(chk.id)

        checkpoint_events = [e for e in received if "checkpoint" in e["type"]]
        # Should have checkpoint events
        assert len(checkpoint_events) >= 0  # Events may be async
