"""
ClawSwarm 单元测试

运行: python -m pytest tests/
"""

import os
import sys
import json
import asyncio
import tempfile
import shutil
from pathlib import Path
from datetime import datetime
from unittest.mock import Mock, patch, AsyncMock

import pytest

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── 测试夹具 ─────────────────────────────────────────────────────────

@pytest.fixture
def temp_dir():
    """创建临时目录"""
    temp = tempfile.mkdtemp()
    yield temp
    shutil.rmtree(temp, ignore_errors=True)


@pytest.fixture
def swarm_dir(temp_dir):
    """创建临时 swarm 目录"""
    os.makedirs(os.path.join(temp_dir, "queue"), exist_ok=True)
    os.makedirs(os.path.join(temp_dir, "in_progress"), exist_ok=True)
    os.makedirs(os.path.join(temp_dir, "results"), exist_ok=True)
    os.makedirs(os.path.join(temp_dir, "agents"), exist_ok=True)
    return temp_dir


@pytest.fixture
def sample_task():
    """示例任务"""
    return {
        "id": "test_task_001",
        "type": "general",
        "description": "测试任务",
        "prompt": "这是一个测试任务",
        "mode": "spawn",
        "priority": 1,
        "created_at": datetime.now().isoformat()
    }


@pytest.fixture
def sample_tasks():
    """多个示例任务"""
    return [
        {
            "id": f"task_{i:03d}",
            "type": "general",
            "description": f"测试任务 {i}",
            "mode": "spawn"
        }
        for i in range(10)
    ]


# ── swarm_node 测试 ─────────────────────────────────────────────────

class TestSwarmNode:
    """swarm_node 模块测试"""
    
    def test_import(self):
        """测试导入"""
        import swarm_node
        assert hasattr(swarm_node, 'poll_task')
        assert hasattr(swarm_node, 'complete_task')
        assert hasattr(swarm_node, 'fail_task')
    
    def test_poll_task(self, swarm_dir, sample_task):
        """测试任务轮询"""
        import swarm_node
        
        # 保存任务到队列
        task_file = os.path.join(swarm_dir, "queue", f"{sample_task['id']}.json")
        with open(task_file, "w", encoding="utf-8") as f:
            json.dump(sample_task, f)
        
        # 轮询任务
        swarm_node.BASE_DIR = swarm_dir
        task = swarm_node.poll_task("test_node")
        
        assert task is not None
        assert task["id"] == sample_task["id"]
    
    def test_complete_task(self, swarm_dir, sample_task):
        """测试任务完成"""
        import swarm_node
        
        # 保存任务到 in_progress
        task_file = os.path.join(swarm_dir, "in_progress", f"{sample_task['id']}.json")
        with open(task_file, "w", encoding="utf-8") as f:
            json.dump(sample_task, f)
        
        swarm_node.BASE_DIR = swarm_dir
        swarm_node.complete_task(sample_task["id"], "OK", "test_node")
        
        # 检查结果文件
        result_file = os.path.join(swarm_dir, "results", f"r_{sample_task['id']}.json")
        assert os.path.exists(result_file)
        
        with open(result_file, encoding="utf-8") as f:
            result = json.load(f)
        
        assert result["status"] == "done"
        assert result["result"] == "OK"
    
    def test_fail_task(self, swarm_dir, sample_task):
        """测试任务失败"""
        import swarm_node
        
        # 保存任务到 in_progress
        task_file = os.path.join(swarm_dir, "in_progress", f"{sample_task['id']}.json")
        with open(task_file, "w", encoding="utf-8") as f:
            json.dump(sample_task, f)
        
        swarm_node.BASE_DIR = swarm_dir
        swarm_node.fail_task(sample_task["id"], "Error occurred", "test_node")
        
        # 检查结果文件
        result_file = os.path.join(swarm_dir, "results", f"r_{sample_task['id']}.json")
        assert os.path.exists(result_file)
        
        with open(result_file, encoding="utf-8") as f:
            result = json.load(f)
        
        assert result["status"] == "failed"
        assert result["error"] == "Error occurred"


# ── swarm_scheduler 测试 ───────────────────────────────────────────

class TestSwarmScheduler:
    """swarm_scheduler 模块测试"""
    
    def test_import(self):
        """测试导入"""
        import swarm_scheduler
        assert hasattr(swarm_scheduler, 'Scheduler')
    
    def test_scheduler_init(self, swarm_dir):
        """测试调度器初始化"""
        import swarm_scheduler
        
        scheduler = swarm_scheduler.Scheduler(base_dir=swarm_dir)
        
        assert scheduler.base_dir == swarm_dir
        assert scheduler.poll_interval == 5


# ── Guard 测试 ─────────────────────────────────────────────────────

class TestGuard:
    """Guard 模块测试"""
    
    def test_import(self):
        """测试导入"""
        import guard
        assert hasattr(guard, 'Guard')
        assert hasattr(guard, 'create_guard')
    
    def test_guard_init(self, swarm_dir):
        """测试 Guard 初始化"""
        import guard
        
        g = guard.Guard(swarm_dir, "test_node")
        
        assert g.node_id == "test_node"
        assert g.workspace.endswith("workspace\\test_node")
    
    def test_validate_path(self, swarm_dir):
        """测试路径验证"""
        import guard
        
        g = guard.Guard(swarm_dir, "test_node")
        
        # 允许的路径
        assert g.validate_path(os.path.join(swarm_dir, "queue", "test.json"))
        
        # 禁止的路径（目录穿越）
        assert not g.validate_path(os.path.join(swarm_dir, "..", "test.json"))


# ── Executor 测试 ─────────────────────────────────────────────────

class TestExecutor:
    """Executor 模块测试"""
    
    def test_import(self):
        """测试导入"""
        import executor
        assert hasattr(executor, 'TaskExecutor')
        assert hasattr(executor, 'ExecutionMode')
        assert hasattr(executor, 'TaskStatus')
    
    @pytest.mark.asyncio
    async def test_execute_task(self):
        """测试任务执行"""
        import executor
        
        exec_obj = executor.TaskExecutor()
        
        task = {
            "id": "test_001",
            "mode": "spawn",
            "prompt": "测试任务"
        }
        
        result = await exec_obj.execute(task)
        
        assert result.task_id == "test_001"
        assert result.status == executor.TaskStatus.DONE
    
    @pytest.mark.asyncio
    async def test_execute_parallel(self):
        """测试并行执行"""
        import executor
        
        exec_obj = executor.TaskExecutor(enable_parallel=True)
        
        tasks = [
            {"id": f"task_{i}", "mode": "spawn"}
            for i in range(5)
        ]
        
        results = await exec_obj.execute_parallel(tasks)
        
        assert len(results) == 5
        assert all(r.status == executor.TaskStatus.DONE for r in results)
    
    @pytest.mark.asyncio
    async def test_workflow(self):
        """测试工作流"""
        import executor
        
        exec_obj = executor.TaskExecutor()
        
        task = {
            "id": "workflow_001",
            "mode": "workflow",
            "steps": [
                {"id": "step1", "mode": "spawn", "prompt": "第一步"},
                {"id": "step2", "mode": "spawn", "prompt": "第二步"},
            ]
        }
        
        result = await exec_obj.execute(task)
        
        assert result.status == executor.TaskStatus.DONE
        assert result.output["mode"] == "workflow"
        assert result.output["steps"] == 2


# ── Monitor 测试 ─────────────────────────────────────────────────

class TestMonitor:
    """Monitor 模块测试"""
    
    def test_import(self):
        """测试导入"""
        import monitor
        assert hasattr(monitor, 'MonitorService')
        assert hasattr(monitor, 'MetricsCollector')
    
    def test_metrics_collector(self):
        """测试指标收集"""
        import monitor
        
        mc = monitor.MetricsCollector()
        
        # 计数器
        mc.inc("test_counter")
        mc.inc("test_counter", 2)
        assert mc.get_counter("test_counter") == 3
        
        # 仪表
        mc.set_gauge("test_gauge", 100)
        assert mc.get_gauge("test_gauge") == 100
        
        # 直方图
        mc.observe("test_histogram", 10)
        mc.observe("test_histogram", 20)
        mc.observe("test_histogram", 30)
        
        stats = mc.get_histogram_stats("test_histogram")
        assert stats["count"] == 3
        assert stats["mean"] == 20
    
    def test_monitor_service(self):
        """测试监控服务"""
        import monitor
        
        svc = monitor.MonitorService()
        svc.start()
        
        # 记录指标
        svc.record_counter("test_requests")
        svc.record_gauge("active_users", 50)
        
        # 节点
        svc.register_node("node-1")
        svc.node_heartbeat("node-1", {"cpu_percent": 25})
        
        # 状态
        status = svc.get_status()
        
        assert status["running"] is True
        assert status["nodes"]["total"] == 1
        assert status["nodes"]["online"] == 1
        
        svc.stop()


# ── Config 测试 ─────────────────────────────────────────────────

class TestConfig:
    """Config 模块测试"""
    
    def test_import(self):
        """测试导入"""
        import config
        assert hasattr(config, 'ConfigManager')
        assert hasattr(config, 'DEFAULT_CONFIG_SCHEMA')
    
    def test_config_manager(self, temp_dir):
        """测试配置管理器"""
        import config
        
        cm = config.ConfigManager(base_dir=temp_dir)
        
        # 设置默认值
        cm.set_schema(config.DEFAULT_CONFIG_SCHEMA)
        
        # 获取值
        assert cm.get("swarm.name") == "ClawSwarm"
        assert cm.get("server.port", 8080) == 8080
        
        # 运行时覆盖
        cm.set("server.port", 9000)
        assert cm.get("server.port") == 9000
        
        # 嵌套值
        cm.set("executor.max_workers", 10)
        assert cm.get("executor.max_workers") == 10
    
    def test_env_loading(self, temp_dir):
        """测试环境变量加载"""
        import config
        
        # 设置环境变量
        os.environ["CLAW_SERVER_PORT"] = "8888"
        
        cm = config.ConfigManager(base_dir=temp_dir, env_prefix="CLAW")
        cm.load_env()
        
        assert cm.get("server.port") == 8888
        
        # 清理
        del os.environ["CLAW_SERVER_PORT"]
    
    def test_to_dict(self, temp_dir):
        """测试配置导出"""
        import config
        
        cm = config.ConfigManager(base_dir=temp_dir)
        cm.set_schema(config.DEFAULT_CONFIG_SCHEMA)
        cm.set("custom.key", "value")
        
        d = cm.to_dict()
        
        assert "swarm" in d
        assert "server" in d
        assert d["custom"]["key"] == "value"


# ── 集成测试 ─────────────────────────────────────────────────────

class TestIntegration:
    """集成测试"""
    
    @pytest.mark.asyncio
    async def test_end_to_end(self, swarm_dir, sample_tasks):
        """端到端测试"""
        import swarm_node
        import executor
        
        # 1. 添加任务到队列
        for task in sample_tasks[:5]:
            task_file = os.path.join(swarm_dir, "queue", f"{task['id']}.json")
            with open(task_file, "w", encoding="utf-8") as f:
                json.dump(task, f)
        
        # 2. 轮询任务
        swarm_node.BASE_DIR = swarm_dir
        task = swarm_node.poll_task("test_node")
        
        assert task is not None
        
        # 3. 执行任务
        exec_obj = executor.TaskExecutor()
        result = await exec_obj.execute(task)
        
        assert result.status == executor.TaskStatus.DONE
        
        # 4. 完成任务
        swarm_node.complete_task(task["id"], result.output, "test_node")
        
        # 5. 验证结果
        result_file = os.path.join(swarm_dir, "results", f"r_{task['id']}.json")
        assert os.path.exists(result_file)


# ── 性能测试 ─────────────────────────────────────────────────────

class TestPerformance:
    """性能测试"""
    
    @pytest.mark.asyncio
    async def test_high_concurrency(self):
        """高并发测试"""
        import executor
        
        # 100 个并发任务
        tasks = [{"id": f"perf_{i}", "mode": "spawn"} for i in range(100)]
        
        exec_obj = executor.TaskExecutor(enable_parallel=True)
        
        import time
        start = time.time()
        
        results = await exec_obj.execute_parallel(tasks)
        
        duration = time.time() - start
        
        assert len(results) == 100
        print(f"\n100 并发任务耗时: {duration:.2f}s")
        assert duration < 10  # 应该很快完成


# ── 运行测试 ─────────────────────────────────────────────────────

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
