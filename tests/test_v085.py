"""Tests for v0.8.5 features: dead_letter, health_scorer, result_pipeline"""
import json
import os
import sys
import time
import tempfile
import pytest

# Add project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── Dead Letter Queue Tests ──────────────────────────────────────────

class TestDeadLetter:
    def setup_method(self):
        import dead_letter
        self.dlq = dead_letter
        # Ensure dir exists and clean up
        os.makedirs(self.dlq.DEAD_LETTER_DIR, exist_ok=True)
        for f in os.listdir(self.dlq.DEAD_LETTER_DIR):
            os.remove(os.path.join(self.dlq.DEAD_LETTER_DIR, f))

    def test_enqueue(self):
        task = {"id": "task_001", "prompt": "test", "retry_count": 3, "max_retries": 3}
        entry_id = self.dlq.enqueue(task, self.dlq.DeadLetterReason.MAX_RETRIES, "Task failed 3 times")
        assert entry_id.startswith("dlq_")
        assert os.path.exists(os.path.join(self.dlq.DEAD_LETTER_DIR, f"{entry_id}.json"))

    def test_list_entries(self):
        tasks = [
            {"id": f"task_{i}", "prompt": f"test {i}", "retry_count": 3, "max_retries": 3}
            for i in range(3)
        ]
        for t in tasks:
            self.dlq.enqueue(t, self.dlq.DeadLetterReason.MAX_RETRIES)

        entries = self.dlq.list_entries()
        assert len(entries) == 3

    def test_list_by_reason(self):
        self.dlq.enqueue({"id": "t1"}, self.dlq.DeadLetterReason.MAX_RETRIES)
        self.dlq.enqueue({"id": "t2"}, self.dlq.DeadLetterReason.TIMEOUT)

        entries = self.dlq.list_entries(reason=self.dlq.DeadLetterReason.TIMEOUT)
        assert len(entries) == 1
        assert entries[0]["original_task_id"] == "t2"

    def test_retry(self):
        task = {"id": "retry_task", "prompt": "retry me", "retry_count": 0, "max_retries": 3}
        entry_id = self.dlq.enqueue(task, self.dlq.DeadLetterReason.NODE_FAILURE)

        new_task_id = self.dlq.retry(entry_id)
        assert new_task_id is not None
        assert new_task_id.startswith("retry_")

        # Entry should be removed from DLQ
        assert not os.path.exists(os.path.join(self.dlq.DEAD_LETTER_DIR, f"{entry_id}.json"))

        # New task should be in queue
        queue_dir = os.path.join(self.dlq.BASE_DIR, "queue")
        assert os.path.exists(os.path.join(queue_dir, f"{new_task_id}.json"))

    def test_purge(self):
        for i in range(5):
            self.dlq.enqueue({"id": f"t{i}"}, self.dlq.DeadLetterReason.MAX_RETRIES)

        count = self.dlq.purge()
        assert count == 5
        assert len(self.dlq.list_entries()) == 0

    def test_stats(self):
        self.dlq.enqueue({"id": "t1"}, self.dlq.DeadLetterReason.MAX_RETRIES)
        self.dlq.enqueue({"id": "t2"}, self.dlq.DeadLetterReason.MAX_RETRIES)
        self.dlq.enqueue({"id": "t3"}, self.dlq.DeadLetterReason.TIMEOUT)

        stats = self.dlq.stats()
        assert stats["total"] == 3
        assert stats["by_reason"]["max_retries_exceeded"] == 2
        assert stats["by_reason"]["execution_timeout"] == 1

    def test_retry_nonexistent(self):
        result = self.dlq.retry("nonexistent")
        assert result is None


# ── Health Scorer Tests ──────────────────────────────────────────────

class TestHealthScorer:
    def setup_method(self):
        import health_scorer
        self.hs = health_scorer

    def test_healthy_node(self):
        report = self.hs.compute_health(
            node_id="node_1",
            last_heartbeat_ts=time.time(),
            successful_tasks=100,
            failed_tasks=0,
            cpu_percent=10,
            memory_percent=30,
            avg_response_ms=100,
        )
        assert report.score >= 80
        assert report.level == self.hs.HealthLevel.HEALTHY
        assert report.should_accept_tasks is True

    def test_degraded_node(self):
        report = self.hs.compute_health(
            node_id="node_2",
            last_heartbeat_ts=time.time() - 45,
            successful_tasks=50,
            failed_tasks=10,
            cpu_percent=60,
            memory_percent=50,
        )
        assert 60 <= report.score < 80
        assert report.level == self.hs.HealthLevel.DEGRADED

    def test_critical_node(self):
        report = self.hs.compute_health(
            node_id="node_3",
            last_heartbeat_ts=time.time() - 300,
            successful_tasks=10,
            failed_tasks=90,
            cpu_percent=95,
            memory_percent=95,
        )
        assert report.score < 40
        assert report.level == self.hs.HealthLevel.CRITICAL
        assert report.should_accept_tasks is False

    def test_no_heartbeat(self):
        report = self.hs.compute_health(
            node_id="node_4",
            last_heartbeat_ts=None,
        )
        assert report.score < 80  # No heartbeat but neutral defaults keep it above 0

    def test_sort_nodes(self):
        reports = [
            self.hs.compute_health("bad", cpu_percent=90, failed_tasks=50, successful_tasks=10),
            self.hs.compute_health("good", cpu_percent=10, successful_tasks=100, failed_tasks=0, last_heartbeat_ts=time.time()),
            self.hs.compute_health("ok", cpu_percent=50),
        ]
        sorted_nodes = self.hs.get_sorted_nodes(reports)
        assert sorted_nodes[0].node_id == "good"

    def test_breakdown_keys(self):
        report = self.hs.compute_health(node_id="x")
        for key in ["heartbeat", "success_rate", "load", "response_time", "error_rate"]:
            assert key in report.breakdown


# ── Result Pipeline Tests ────────────────────────────────────────────

class TestResultPipeline:
    def setup_method(self):
        import result_pipeline
        self.rp = result_pipeline
        # Clean up pipelines dir
        if os.path.exists(self.rp.PIPELINE_DIR):
            for f in os.listdir(self.rp.PIPELINE_DIR):
                os.remove(os.path.join(self.rp.PIPELINE_DIR, f))

    def _write_result(self, label, status="success", output="test output"):
        results_dir = self.rp.RESULTS_DIR
        os.makedirs(results_dir, exist_ok=True)
        ts = int(time.time() * 1000)
        filepath = os.path.join(results_dir, f"r_test_{label}_{ts}.json")
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump({"status": status, "output": output, "label": label}, f)
        return filepath

    def test_pipeline_collect(self):
        self._write_result("alpha")
        pipeline = self.rp.ResultPipeline()
        assert pipeline.collect("alpha", timeout=5) is True
        assert "alpha" in pipeline._results

    def test_pipeline_filter(self):
        self._write_result("good", status="success")
        self._write_result("bad", status="failed")
        pipeline = self.rp.ResultPipeline()
        pipeline.collect("good", timeout=5)
        pipeline.collect("bad", timeout=5)
        removed = pipeline.filter_failed()
        assert removed == 1
        assert "good" in pipeline._results
        assert "bad" not in pipeline._results

    def test_pipeline_transform(self):
        self._write_result("test_label", output="hello world")
        pipeline = self.rp.ResultPipeline()
        pipeline.collect("test_label", timeout=5)
        outputs = pipeline.transform()
        assert "test_label" in outputs
        assert outputs["test_label"] == "hello world"

    def test_pipeline_aggregate(self):
        outputs = {"a": "output A", "b": "output B"}
        pipeline = self.rp.ResultPipeline()
        result = pipeline.aggregate(outputs)
        assert "## a" in result
        assert "output A" in result
        assert "## b" in result

    def test_pipeline_export(self):
        pipeline = self.rp.ResultPipeline()
        filepath = pipeline.export("test content")
        assert os.path.exists(filepath)
        with open(filepath, encoding="utf-8") as f:
            data = json.load(f)
        assert data["content"] == "test content"
        assert "metadata" in data

    def test_pipeline_summary(self):
        self._write_result("s1")
        pipeline = self.rp.ResultPipeline()
        pipeline.collect("s1", timeout=5)
        summary = pipeline.summary()
        assert summary["collected"] == 1
        assert "s1" in summary["labels"]

    def test_quick_aggregate(self):
        self._write_result("q1", output="result 1")
        self._write_result("q2", output="result 2")
        result = self.rp.quick_aggregate(["q1", "q2"], timeout=5)
        assert "result 1" in result
        assert "result 2" in result


# ── MCP Server Integration Tests ─────────────────────────────────────

class TestMCPServer:
    def test_mcp_server_initialization(self):
        """Verify MCP server can be imported and has tools registered"""
        import mcp_server
        server = mcp_server.MCPStdioServer()
        mcp_server.setup_tools(server)
        assert len(server._tools) == 11
        assert "clawswarm_dead_letter" in server._tools
        assert "clawswarm_health" in server._tools

    def test_mcp_dead_letter_tool(self):
        import mcp_server
        server = mcp_server.MCPStdioServer()
        mcp_server.setup_tools(server)
        handler = server._tools["clawswarm_dead_letter"]["handler"]
        result = handler({"action": "stats"})
        assert "total" in result

    def test_mcp_health_tool(self):
        import mcp_server
        server = mcp_server.MCPStdioServer()
        mcp_server.setup_tools(server)
        handler = server._tools["clawswarm_health"]["handler"]
        result = handler({
            "node_id": "test_node",
            "cpu": 10,
            "memory": 20,
            "successful_tasks": 100,
            "failed_tasks": 0,
            "avg_response_ms": 100,
        })
        assert result["score"] >= 60
        assert result["level"] in ("healthy", "degraded")
