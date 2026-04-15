"""
ClawSwarm 使用示例

本文件展示 ClawSwarm 的各种使用方式
"""

import asyncio
import os
import sys
import json
import time
from datetime import datetime

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── 示例 1: 基本任务队列 ─────────────────────────────────────────────

def example_basic_queue():
    """示例 1: 基本任务队列"""
    print("=" * 60)
    print("示例 1: 基本任务队列")
    print("=" * 60)
    
    import swarm_node
    import swarm_scheduler
    
    # 配置
    swarm_dir = r"D:\claw\swarm"
    swarm_node.BASE_DIR = swarm_dir
    swarm_scheduler.BASE_DIR = swarm_dir
    
    # 添加任务
    task = {
        "id": f"task_{datetime.now().strftime('%Y%m%d%H%M%S')}",
        "type": "general",
        "description": "示例任务",
        "prompt": "你好，这是一个测试任务"
    }
    
    # 保存到队列
    task_file = os.path.join(swarm_dir, "queue", f"{task['id']}.json")
    with open(task_file, "w", encoding="utf-8") as f:
        json.dump(task, f, ensure_ascii=False)
    
    print(f"✅ 已添加任务: {task['id']}")
    
    # 轮询任务（模拟节点）
    polled = swarm_node.poll_task("node_demo")
    if polled:
        print(f"📥 节点轮询到任务: {polled['id']}")
        
        # 执行任务
        result = swarm_node.execute_task(polled, "node_demo")
        
        # 完成任务
        swarm_node.complete_task(polled["id"], result, "node_demo")
        print(f"✅ 任务完成: {result}")
    
    print()


# ── 示例 2: Guard 隔离 ─────────────────────────────────────────────

def example_guard():
    """示例 2: Guard 安全隔离"""
    print("=" * 60)
    print("示例 2: Guard 安全隔离")
    print("=" * 60)
    
    import guard
    
    # 创建 Guard 实例
    g = guard.Guard(r"D:\claw\swarm", "node_001")
    
    print(f"节点工作目录: {g.workspace}")
    
    # 测试路径验证
    test_paths = [
        r"D:\claw\swarm\queue\task.json",
        r"D:\claw\swarm\..\secret.txt",
        r"C:\Windows\System32\cmd.exe",
    ]
    
    for path in test_paths:
        result = g.validate_path(path)
        print(f"  {'✅' if result else '❌'} {path}: {'允许' if result else '禁止'}")
    
    # 测试命令验证
    test_commands = [
        "ls -la",
        "echo hello",
        "rm -rf /",
        "format c:",
    ]
    
    for cmd in test_commands:
        result = g.validate_command(cmd)
        print(f"  {'✅' if result else '❌'} {cmd}: {'允许' if result else '禁止'}")
    
    # 审计日志
    g.audit("test_event", {"message": "测试审计"})
    print("\n✅ 审计日志已记录")
    
    print()


# ── 示例 3: Executor 执行器 ─────────────────────────────────────────

async def example_executor():
    """示例 3: Executor 执行器"""
    print("=" * 60)
    print("示例 3: Executor 执行器")
    print("=" * 60)
    
    import executor
    
    # 创建执行器
    exec_obj = executor.TaskExecutor(
        max_workers=5,
        default_timeout=60
    )
    
    # 注册回调
    exec_obj.on("on_success", lambda r: print(f"✅ 任务完成: {r.task_id}"))
    exec_obj.on("on_failure", lambda r: print(f"❌ 任务失败: {r.task_id} - {r.error}"))
    
    # 单任务执行
    task = {
        "id": "exec_001",
        "mode": "spawn",
        "prompt": "写一首关于 AI 的诗",
        "model": "claude-3"
    }
    
    print("执行任务...")
    result = await exec_obj.execute(task)
    
    print(f"\n结果:")
    print(f"  状态: {result.status.value}")
    print(f"  输出: {result.output}")
    print(f"  耗时: {result.duration_seconds:.2f}s")
    
    # 并行执行
    tasks = [
        {"id": f"parallel_{i}", "mode": "spawn", "prompt": f"任务 {i}"}
        for i in range(5)
    ]
    
    print("\n并行执行 5 个任务...")
    results = await exec_obj.execute_parallel(tasks)
    
    print(f"完成: {len(results)} 个任务")
    print(f"统计: {exec_obj.get_stats()}")
    
    print()


# ── 示例 4: Monitor 监控 ───────────────────────────────────────────

def example_monitor():
    """示例 4: Monitor 监控"""
    print("=" * 60)
    print("示例 4: Monitor 监控")
    print("=" * 60)
    
    import monitor
    
    # 创建监控服务
    svc = monitor.MonitorService()
    svc.start()
    
    # 注册节点
    svc.register_node("node-1", {"capability": "web"})
    svc.register_node("node-2", {"capability": "compute"})
    svc.register_node("node-3", {"capability": "data"})
    
    # 模拟心跳
    svc.node_heartbeat("node-1", {
        "cpu_percent": 25.5,
        "memory_percent": 40.0,
        "tasks_completed": 10
    })
    
    svc.node_heartbeat("node-2", {
        "cpu_percent": 75.0,
        "memory_percent": 60.0,
        "tasks_completed": 5
    })
    
    # 记录指标
    svc.record_counter("requests_total", 1)
    svc.record_counter("requests_total", 1)
    svc.record_counter("requests_total", 1)
    
    svc.record_gauge("active_users", 100)
    svc.record_gauge("queue_size", 5)
    
    # 计时
    start = svc.start_timer("task_duration")
    time.sleep(0.1)
    svc.stop_timer("task_duration", start)
    
    # 获取状态
    status = svc.get_status()
    
    print(f"节点统计:")
    for node in status["nodes"]["list"]:
        print(f"  {node['node_id']}: {node['status']} (CPU: {node['cpu']}%)")
    
    print(f"\n指标:")
    print(f"  requests_total: {status['metrics']['counters'].get('requests_total', 0)}")
    print(f"  active_users: {status['metrics']['gauges'].get('active_users', 0)}")
    
    # Prometheus 格式
    print(f"\nPrometheus 格式:")
    print(svc.get_metrics_prometheus())
    
    svc.stop()
    
    print()


# ── 示例 5: Config 配置 ─────────────────────────────────────────────

def example_config():
    """示例 5: Config 配置"""
    print("=" * 60)
    print("示例 5: Config 配置")
    print("=" * 60)
    
    import config
    
    # 创建配置管理器
    cm = config.ConfigManager(base_dir=r"D:\claw\swarm", env_prefix="CLAW")
    
    # 设置模式
    cm.set_schema(config.DEFAULT_CONFIG_SCHEMA)
    
    # 运行时覆盖
    cm.set("swarm.name", "ClawSwarm-Pro")
    cm.set("swarm.max_nodes", 20)
    cm.set("server.port", 9000)
    cm.set("monitor.enabled", True)
    
    # 环境变量
    os.environ["CLAW_EXECUTOR_MAX_WORKERS"] = "10"
    cm.load_env()
    
    # 获取值
    print(f"集群名称: {cm.get('swarm.name')}")
    print(f"最大节点: {cm.get('swarm.max_nodes')}")
    print(f"服务器端口: {cm.get('server.port')}")
    print(f"工作线程: {cm.get('executor.max_workers')}")
    print(f"监控启用: {cm.get('monitor.enabled')}")
    
    # 完整配置
    print(f"\n完整配置哈希: {cm.get_hash()}")
    
    print()


# ── 示例 6: 工作流 ─────────────────────────────────────────────────

async def example_workflow():
    """示例 6: 工作流"""
    print("=" * 60)
    print("示例 6: 工作流")
    print("=" * 60)
    
    import executor
    
    exec_obj = executor.TaskExecutor()
    
    # 定义工作流
    workflow = {
        "id": "workflow_001",
        "mode": "workflow",
        "steps": [
            {
                "id": "step1",
                "mode": "fetch",
                "url": "https://example.com",
                "description": "获取网页内容"
            },
            {
                "id": "step2",
                "mode": "spawn",
                "prompt": "总结这个网页的内容",
                "description": "分析内容"
            },
            {
                "id": "step3",
                "mode": "spawn",
                "prompt": "提取关键信息为 JSON",
                "description": "提取数据"
            }
        ]
    }
    
    print("执行工作流...")
    result = await exec_obj.execute(workflow)
    
    print(f"\n工作流结果:")
    print(f"  状态: {result.status.value}")
    print(f"  步骤数: {result.output.get('steps', 0)}")
    print(f"  耗时: {result.duration_seconds:.2f}s")
    
    print()


# ── 示例 7: 调度器 ─────────────────────────────────────────────────

def example_scheduler():
    """示例 7: 调度器"""
    print("=" * 60)
    print("示例 7: 调度器")
    print("=" * 60)
    
    import swarm_scheduler
    
    # 创建调度器
    sched = swarm_scheduler.Scheduler(
        base_dir=r"D:\claw\swarm",
        poll_interval=5
    )
    
    # 添加任务
    tasks = [
        {
            "id": f"scheduled_{i}",
            "type": "scheduled",
            "description": f"定时任务 {i}",
            "cron": f"*/{i+1} * * * *"  # 每 N 分钟
        }
        for i in range(3)
    ]
    
    for task in tasks:
        sched.add_task(task)
    
    print(f"已添加 {len(tasks)} 个定时任务")
    
    # 获取状态
    status = sched.get_status()
    print(f"待执行: {status['pending']}")
    print(f"进行中: {status['running']}")
    
    print()


# ── 主函数 ─────────────────────────────────────────────────────────

async def main():
    """运行所有示例"""
    print("\n" + "=" * 60)
    print("ClawSwarm 使用示例")
    print("=" * 60 + "\n")
    
    # 示例 1: 基本任务队列
    example_basic_queue()
    
    # 示例 2: Guard 隔离
    example_guard()
    
    # 示例 3: Executor 执行器
    await example_executor()
    
    # 示例 4: Monitor 监控
    example_monitor()
    
    # 示例 5: Config 配置
    example_config()
    
    # 示例 6: 工作流
    await example_workflow()
    
    # 示例 7: 调度器
    example_scheduler()
    
    print("=" * 60)
    print("所有示例完成!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
